# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

#from openerp.osv import osv, orm
#from datetime import time, datetime
#from openerp.tools.translate import _
#from openerp import models, fields


import pytz
import re
import time
import openerp
import openerp.service.report
import uuid
import collections
import babel.dates
from werkzeug.exceptions import BadRequest
from datetime import datetime, timedelta
from dateutil import parser
from dateutil import rrule
from dateutil.relativedelta import relativedelta
from openerp import api
from openerp import tools, SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
from openerp.http import request
from operator import itemgetter
from openerp.exceptions import UserError
from openerp.exceptions import ValidationError
import logging
from openerp.osv import orm
import calendar
import pprint

import openerp.addons.cheques_de_terceros
import openerp.addons.descuento_de_cheques
import subcuenta
_logger = logging.getLogger(__name__)
#       _logger.error("date now : %r", date_now)

class plazo_fijo(osv.Model):
    _name = 'plazo.fijo'
    _description = 'Modulo para el calculo y gestion de plazos fijos (Deudas/Proveedores)'
    _rec_name = "display_name"

    _columns = {
        'fecha': fields.date('Fecha', required=True),
        'state': fields.selection([('borrador', 'Borrador'), ('generado', 'Generado'), ('confirmado', 'Confirmado'), ('pagado', 'Pagado')], string='Estado', readonly=True),
        'active': fields.boolean("Activa"),
        'display_name': fields.char("Nombre", compute='_compute_display_name', readonly=True),

        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta', required=True),
        
        'journal_cobro_id': fields.many2one('account.journal', 'Metodo de cobro', domain="[('type', '=', 'cash')]", required=True),
        'move_capital_id': fields.many2one('account.move', 'Asiento del capital', readonly=True),
        'monto': fields.float('Monto', required=True),
        'tasa_pasiva': fields.float('Tasa mensual a pagar', required=True),
        'cuotas': fields.integer('Plazo en meses', required=True),
        'fecha_primer_vencimiento': fields.date('Fecha primer vencimiento', required=True),
        'respetar_dias_primer_vencimiento': fields.boolean('Respetar dias primer vencimiento'),
        'cuotas_ids': fields.one2many('plazo.fijo.cuota', 'plazo_fijo_id', 'Cuotas'),

    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
        'active': True,
        'respetar_dias_primer_vencimiento': True,
    }

    @api.one
    @api.depends('cuenta_entidad_id')
    def _compute_display_name(self):
        if self.cuenta_entidad_id:
            self.display_name = self.cuenta_entidad_id.display_name + ' Plazo Fijo ' + str(self.id)

    @api.multi
    def confirmar(self, cr):
        self.state = 'confirmado'
        self.move_capital_id.state = 'posted'
        for cuota in self.cuotas_ids:
            cuota.state = 'pendiente'
        return True

    def editar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'borrador'}, context=None)
        return True

    @api.multi
    def cancelar(self, cr):
        self.state = 'borrador'
        self.move_capital_id.unlink()
        for cuota in self.cuotas_ids:
            cuota.unlink()
        return True

    
    def caclular_fechas_de_vencimientos(self):
        ret = []
        fecha_primer_vencimiento = self.fecha_primer_vencimiento
        fecha_primer_vencimiento_obj = datetime.strptime(str(fecha_primer_vencimiento), "%Y-%m-%d")
        cantidad_de_cuotas = self.cuotas

        if fecha_primer_vencimiento_obj.day > 28:
            raise ValidationError("Fecha mayor al dia 28 no es correcta.")
        else:
            ret.append(fecha_primer_vencimiento_obj)
            day = fecha_primer_vencimiento_obj.day
            month = fecha_primer_vencimiento_obj.month
            year = fecha_primer_vencimiento_obj.year
            i = 1
            while i < cantidad_de_cuotas:
                month = month + 1
                if month > 12:
                    month = 1
                    year = year + 1
                fecha_str = str(year)+"-"+str(month)+"-"+str(day)
                fecha_vencimiento = datetime.strptime(str(fecha_str), "%Y-%m-%d")
                ret.append(fecha_vencimiento)
                i = i + 1
        return ret

    def _crear_asiento_capital(self):
        line_ids = []

        # create move line
        # Debito el monto del interes a la cuenta seleccionada en journal_intereses_id
        aml = {
            'date': self.fecha,
            'account_id': self.journal_cobro_id.default_debit_account_id.id,
            'name': 'Recibo Capital / ' + self.cuenta_entidad_id.display_name,
            'partner_id': self.cuenta_entidad_id.entidad_id.id,
            'debit': self.monto,
        }
        line_ids.append((0,0,aml))

        aml2 = {
            'date': self.fecha,
            'account_id': self.cuenta_entidad_id.account_pagar_id.id,
            'name': 'Capital en Plazo Fijo ' + self.display_name,
            'partner_id': self.cuenta_entidad_id.entidad_id.id,
            'credit': self.monto,
        }
        line_ids.append((0,0,aml2))

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        # create move
        move_name = 'Plazo Fijo/CAPITAL/' + self.display_name
        move = self.env['account.move'].create({
            'name': move_name,
            'date': self.fecha,
            'journal_id': self.journal_cobro_id.id,
            'state':'draft',
            'company_id': company_id,
            'partner_id': self.cuenta_entidad_id.entidad_id.id,
            'line_ids': line_ids,
        })
        #move.state = 'posted'
        self.move_capital_id = move.id


    @api.multi
    def hola(self, cr):
        self.cancelar(cr)
        self.state = 'generado'
        self._crear_asiento_capital()
        cuotas_ids = []
        fechas_de_vencimientos = self.caclular_fechas_de_vencimientos()
        fecha = None
        monto = 0
        i = 1
        is_capital = False
        while i <= (self.cuotas + 1):
            
            if i == (self.cuotas + 1):
                monto = self.monto
                fecha = fechas_de_vencimientos[i-2]
                is_capital = True
            else:
                if i == 1 and self.respetar_dias_primer_vencimiento:
                    fecha_inicial = datetime.strptime(str(self.fecha), "%Y-%m-%d")
                    fecha_final = datetime.strptime(str(self.fecha_primer_vencimiento), "%Y-%m-%d")
                    diferencia = fecha_final - fecha_inicial
                    dias = diferencia.days
                else:
                    dias = 30
                monto = self.monto * dias * (self.tasa_pasiva / 30 / 100)
                fecha = fechas_de_vencimientos[i-1]

            val = {
                    'fecha': fecha,
                    'state': 'borrador',
                    'display_name': 'Cuota ' + str(i),
                    'plazo_fijo_id': self.id,
                    'monto': monto,
                    'is_capital': is_capital,
            }
            
            cuota_n = self.env['plazo.fijo.cuota'].create(val)
            cuotas_ids.append(cuota_n.id)
            i = i + 1
        
        self.cuotas_ids = cuotas_ids

        return True

class plazo_fijo_cuota(osv.Model):
    _name = 'plazo.fijo.cuota'
    _description = 'Informacion de las cuotas'
    _rec_name = "display_name"
    _order = "fecha"
    _columns = {
        'fecha': fields.date('Fecha', required=True),
        'state': fields.selection([('borrador', 'Borrador'), ('pendiente', 'Pendiente'), ('pagada', 'Pagada')], string='Estado', readonly=True),
        'display_name': fields.char("Nombre", readonly=True),
        'plazo_fijo_id': fields.many2one('plazo.fijo', 'Plazo Fijo'),
        'is_capital': fields.boolean("Es Capital", readonly=True),
        
        'move_cuota_id': fields.many2one('account.move', 'Asiento de la cuota', readonly=True),
        'journal_intereses_id': fields.many2one('account.journal', 'Diario intereses', domain="[('type', 'in', ('sale', 'purchase'))]"),
        'monto': fields.float('Monto', required=True),
        'detalle': fields.char('Detalle'),

        'journal_pago_id': fields.many2one('account.journal', 'Metodo de pago', domain="[('type', 'in', ('cash', 'bank'))]"),
        'fecha_de_pago': fields.date('Fecha de pago'),
        'move_pago_id': fields.many2one('account.move', 'Asiento del pago', readonly=True),

    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
        'active': True,
    }

    def _crear_asiento_intereses(self):
        line_ids = []

        if not self.is_capital:

            # create move line
            # Debito el monto del interes a la cuenta seleccionada en journal_intereses_id
            aml = {
                'date': self.fecha,
                'account_id': self.journal_intereses_id.default_debit_account_id.id,
                'name': 'Intereses a pagar / ' + self.plazo_fijo_id.display_name,
                'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
                'debit': self.monto,
            }
            line_ids.append((0,0,aml))

            aml2 = {
                'date': self.fecha,
                'account_id': self.plazo_fijo_id.cuenta_entidad_id.account_pagar_id.id,
                'name': 'Intereses a pagar / Tasa ' + str(self.plazo_fijo_id.tasa_pasiva) + '%',
                'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
                'credit': self.monto,
            }
            line_ids.append((0,0,aml2))

            company_id = self.env['res.users'].browse(self.env.uid).company_id.id
            # create move
            move_name = 'Plazo Fijo/GENERA/' + self.display_name + '/Intereses'
            move = self.env['account.move'].create({
                'name': move_name,
                'date': self.fecha,
                'journal_id': self.journal_intereses_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
                'line_ids': line_ids,
            })
            move.state = 'posted'
            self.move_cuota_id = move.id

    def _pagar_cuota(self):
        line_ids = []

        name = None
        name2 = None
        if self.is_capital:
            name = 'Devolucion Capital / ' + self.plazo_fijo_id.display_name
            name2 = 'Devolucion Capital / ' + self.plazo_fijo_id.display_name
        else:
            name = 'Intereses pagados / ' + self.plazo_fijo_id.display_name
            name2 = 'Intereses a pagar / Tasa ' + str(self.plazo_fijo_id.tasa_pasiva) + '%'


        # create move line
        # 
        aml = {
            'date': self.fecha_de_pago,
            'account_id': self.journal_pago_id.default_debit_account_id.id,
            'name': name,
            'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
            'credit': self.monto,
        }
        line_ids.append((0,0,aml))

        aml2 = {
            'date': self.fecha_de_pago,
            'account_id': self.plazo_fijo_id.cuenta_entidad_id.account_pagar_id.id,
            'name': name2,
            'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
            'debit': self.monto,
        }
        line_ids.append((0,0,aml2))

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        # create move
        move_name = 'Plazo Fijo/PAGO/' + self.display_name + '/Intereses'
        move = self.env['account.move'].create({
            'name': move_name,
            'date': self.fecha,
            'journal_id': self.journal_pago_id.id,
            'state':'draft',
            'company_id': company_id,
            'partner_id': self.plazo_fijo_id.cuenta_entidad_id.entidad_id.id,
            'line_ids': line_ids,
        })
        move.state = 'posted'
        self.move_pago_id = move.id

    @api.multi
    def pagar(self, cr):
        if not self.move_cuota_id:
            self._crear_asiento_intereses()
        self._pagar_cuota()
        self.state = 'pagada'

        #Para setear si el Plazo Fijo esta pagado.
        flag_pagado = True
        for cuota in self.plazo_fijo_id.cuotas_ids:
            if cuota.state != 'pagada':
                flag_pagado = False
        if flag_pagado and len(self.plazo_fijo_id.cuotas_ids) > 1:
            self.plazo_fijo_id.state = 'pagado'

        return True

    def editar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'borrador'}, context=None)
        return True
