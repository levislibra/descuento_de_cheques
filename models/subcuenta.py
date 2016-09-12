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
from openerp import api, models
from openerp import tools, SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
from openerp.http import request
from operator import itemgetter
from openerp.exceptions import UserError
from openerp.exceptions import ValidationError

import openerp.addons.cheques_de_terceros
import logging
from openerp.osv import orm

_logger = logging.getLogger(__name__)
#   	_logger.error("date now : %r", date_now)

# Add a new floats fields and date object account_move_line
class account_move_line(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'account.move.line'
    _name = 'account.move.line'
    _description = 'account.move.line'

    _columns = {
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta', readonly=True),
        'interes_generado': fields.boolean('Interes generado'),
        'interes_fijo': fields.boolean('Interes fijo'),
        'sub_saldo': fields.float('Saldo', readonly=True, compute="_compute_sub_saldo"),
        'dias': fields.integer('Dias', readonly=True),
        'tasa_descubierto': fields.float('Tasa descuento', readonly=True),
        'monto_interes': fields.float('Monto interes', readonly=True),
        'saldo': fields.float('Saldo total', readonly=True),
    }

    _defaults = {
    	'interes_generado': False,
        'interes_fijo': False,
        'tasa_descubierto': 0,
    }

class subcuenta(osv.Model):
    _name = 'subcuenta'
    _description = 'subcuenta'
    _columns =  {
        'name': fields.char('Nombre', required=True),
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta'),
        'journal_id': fields.many2one('account.journal', 'Diario'),
        'tipo': fields.selection([('activo', 'Activo'), ('pasivo', 'Pasivo')], string='Tipo', required=True),
        #'account_id': fields.many2one('account.account', 'Cuenta', required=True),
        'descuento_id': fields.many2one('descuento.de.cheques', 'Descuento'),
        'descuento_de_cheques': fields.boolean('Permite descuento de cheques'),
        'tasa_mensual_pagada' : fields.float('Tasa mensual pagada'),
        'tasa_fija_descuento' : fields.float('Tasa Fija Descuento'),
        'tasa_mensual_descuento' : fields.float('Tasa Mensual Descuento'),
        'tasa_descubierto' : fields.float('Tasa Descubierto'),
        'apuntes_ids': fields.one2many('account.move.line', 'subcuenta_id', 'Apuntes', readonly=True),
        'state': fields.selection([('borrador', 'Borrador'), ('activa', 'Activa'), ('cancelada', 'Cancelada')], string='Estado', readonly=True),
        #faltan campos derivados
        #saldo
        'saldo' : fields.float('Saldo', compute="_calcular_saldo", readonly=True),
    }

    @api.one
    def activar(self, cr):
        self.state = 'activa'

    def _cantidad_de_dias(self, fecha_inicial, fecha_final):
        fecha_inicial = datetime.strptime(str(fecha_inicial), "%Y-%m-%d")
        fecha_final = datetime.strptime(str(fecha_final), "%Y-%m-%d")
        diferencia = fecha_final - fecha_inicial
        return diferencia.days
            

    @api.multi
    def button_actualizar_saldo_acumulado(self, cr):
        apunte_previo = None
        flag_divisa = False
        if self.cuenta_entidad_id.currency_id != False and self.cuenta_entidad_id.currency_id.id != 20:
            flag_divisa = True
        apuntes_ids = self.apuntes_ids
        count = len(apuntes_ids)
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            if apunte.tasa_descubierto == -1:
                if self.tipo == 'activo':
                    apunte.tasa_descubierto = self.tasa_descubierto
                elif self.tipo == 'pasivo':
                    apunte.tasa_descubierto = self.tasa_mensual_pagada
            if apunte_previo != None:
                if flag_divisa:
                    apunte.sub_saldo = apunte.amount_currency + apunte_previo.sub_saldo
                else:
                    apunte.sub_saldo = apunte.debit - apunte.credit + apunte_previo.sub_saldo
                apunte.dias = self._cantidad_de_dias(apunte_previo.date, apunte.date)
                
                if not apunte.interes_generado and self.tipo == 'activo' and apunte_previo.saldo > 0 and not apunte.interes_fijo:
                    #if apunte.tasa_descubierto == -1:
                    #    apunte.tasa_descubierto = self.tasa_descubierto
                    apunte.monto_interes = apunte_previo.saldo * apunte.dias * (apunte.tasa_descubierto / 30 / 100)
                elif not apunte.interes_generado and self.tipo == 'pasivo' and apunte_previo.saldo < 0 and not apunte.interes_fijo:
                    #if apunte.tasa_descubierto == -1:
                    #    apunte.tasa_descubierto = self.tasa_mensual_pagada
                    apunte.monto_interes = apunte_previo.saldo * apunte.dias * (apunte.tasa_descubierto / 30 / 100)

                if flag_divisa:
                    apunte.saldo = apunte.amount_currency + apunte.monto_interes + apunte_previo.saldo
                else:
                    apunte.saldo = apunte.debit - apunte.credit + apunte.monto_interes + apunte_previo.saldo
            else:
                if flag_divisa:
                    apunte.sub_saldo = apunte.amount_currency
                    apunte.saldo = apunte.amount_currency
                else:
                    apunte.sub_saldo = apunte.debit - apunte.credit
                    apunte.saldo = apunte.debit - apunte.credit
            apunte_previo = apunte
            i = i + 1

    @api.model
    def _actualizar_saldo_acumulado(self):
        apunte_previo = None
        flag_divisa = False
        if self.cuenta_entidad_id.currency_id.id != 20:
            flag_divisa = True
        apuntes_ids = self.apuntes_ids
        count = len(apuntes_ids)
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            if apunte.tasa_descubierto == -1:
                if self.tipo == 'activo':
                    apunte.tasa_descubierto = self.tasa_descubierto
                elif self.tipo == 'pasivo':
                    apunte.tasa_descubierto = self.tasa_mensual_pagada
            if apunte_previo != None:
                if flag_divisa:
                    apunte.sub_saldo = apunte.amount_currency + apunte_previo.sub_saldo
                else:
                    apunte.sub_saldo = apunte.debit - apunte.credit + apunte_previo.sub_saldo
                apunte.dias = self._cantidad_de_dias(apunte_previo.date, apunte.date)
                
                if not apunte.interes_generado and self.tipo == 'activo' and apunte_previo.saldo > 0 and not apunte.interes_fijo:
                    #if apunte.tasa_descubierto == -1:
                    #    apunte.tasa_descubierto = self.tasa_descubierto
                    apunte.monto_interes = apunte_previo.saldo * apunte.dias * (apunte.tasa_descubierto / 30 / 100)
                elif not apunte.interes_generado and self.tipo == 'pasivo' and apunte_previo.saldo < 0 and not apunte.interes_fijo:
                    #if apunte.tasa_descubierto == -1:
                    #    apunte.tasa_descubierto = self.tasa_mensual_pagada
                    apunte.monto_interes = apunte_previo.saldo * apunte.dias * (apunte.tasa_descubierto / 30 / 100)

                if flag_divisa:
                    apunte.saldo = apunte.amount_currency + apunte.monto_interes + apunte_previo.saldo
                else:
                    apunte.saldo = apunte.debit - apunte.credit + apunte.monto_interes + apunte_previo.saldo
            else:
                if flag_divisa:
                    apunte.sub_saldo = apunte.amount_currency
                    apunte.saldo = apunte.amount_currency
                else:
                    apunte.sub_saldo = apunte.debit - apunte.credit
                    apunte.saldo = apunte.debit - apunte.credit
            apunte_previo = apunte
            i = i + 1

    @api.one
    @api.depends('apuntes_ids')
    def _calcular_saldo(self):
        self.saldo = 0
        flag_divisa = False
        if self.cuenta_entidad_id.currency_id.id != 20:
            flag_divisa = True
        for apunte in self.apuntes_ids:
            if flag_divisa:
                self.saldo += apunte.amount_currency + apunte.monto_interes
            else:
                self.saldo += apunte.debit - apunte.credit + apunte.monto_interes


    def ver_subcuentas(self, cr, uid, ids, context=None):
    	subcuentas_obj = self.pool.get('subcuentas')
    	subcuentas_ids = subcuentas_obj.search(cr, uid, [('active', '=', True)])
    	return {
    			'domain': "[('id', 'in', ["+','.join(map(str, subcuentas_ids))+"])]",
    			'name': ('Subcuentas'),
    			'view_type': 'form',
    			'view_mode': 'tree,form',
    			'res_model': 'subcuenta',
    			'view_id': False,
    			'type': 'ir.actions.act_window',
    			}

    _defaults = {
    	'state': 'borrador',
        'descuento_de_cheques': False,
        'saldo': 0,
    }

class form_opciones_subcuenta_move_line(osv.Model):
    _name = 'form.opciones.subcuenta.move.line'
    _description = 'Opciones para los movimientos de las subcuentas'
    _rec_name= "id"
    _order = "id desc"
    _columns = {
        'id': fields.integer("ID", readonly=True),
        'fecha': fields.date("Fecha", required=True),
        
        'cambiar_tasa': fields.boolean("Cambiar tasa de interes."),
        'tasa_de_interes': fields.float("Tasa de Interes"),

        'fijar_monto_de_interes': fields.boolean("Fijar monto de interes."),
        'monto_interes': fields.float("Monto de Interes"),

        'crear_movimiento': fields.boolean("Crear movimiento para calculo de intereses."),
        'fecha_movimiento': fields.date("Fecha"),

        'asentar_interes': fields.boolean("Asentar intereses."),
        'journal_intereses_id': fields.many2one('account.journal', string="Diario ingresos", domain="[('type', 'in', ('sale', 'purchase'))]"),
        
        'cambiar_subcuenta': fields.boolean("Cambiar Subcuenta."),
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta'),
        'subcuenta_destino_id': fields.many2one('subcuenta', 'Subcuenta destino'),


        #'move_id': fields.many2one("account.move", "Asiento", readonly=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmado', 'Confirmado')], string='Estado', readonly=True),
    }

    #@api.one
    @api.onchange('cambiar_tasa')
    def compute_cambiar_tasa(self):
        self.fijar_monto_de_interes = False
        self.crear_movimiento = False
        self.asentar_interes = False
        self.cambiar_subcuenta = False

    @api.onchange('fijar_monto_de_interes')
    def compute_fijar_monto_de_interes(self):
        self.cambiar_tasa = False
        self.crear_movimiento = False
        self.asentar_interes = False
        self.cambiar_subcuenta = False

    @api.onchange('crear_movimiento')
    def compute_crear_moviemiento(self):
        self.cambiar_tasa = False
        self.fijar_monto_de_interes = False
        self.asentar_interes = False
        self.cambiar_subcuenta = False

    @api.onchange('asentar_interes')
    def compute_asentar_interes(self):
        self.cambiar_tasa = False
        self.fijar_monto_de_interes = False
        self.crear_movimiento = False
        self.cambiar_subcuenta = False

    @api.onchange('cambiar_subcuenta')
    def compute_cambiar_subcuenta(self):
        self.cambiar_tasa = False
        self.fijar_monto_de_interes = False
        self.crear_movimiento = False
        self.asentar_interes = False


    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'generar_intereses': False,
        'state': 'borrador',
    }

    @api.model
    def default_get(self, fields):
        rec = super(form_opciones_subcuenta_move_line, self).default_get(fields)
        context = dict(self._context or {})
        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        movimientos = self._get_movimientos()

        # Checks on context parameters
        if not active_model or not active_ids:
            raise UserError(_("Programmation error: wizard action executed without active_model or active_ids in context."))
        if active_model != 'account.move.line':
            raise UserError(_("Programmation error: the expected model for this action is 'account.move.line'. The provided one is '%d'.") % active_model)

        rec.update({
            'fecha_movimiento': movimientos[0].date,
            'cuenta_entidad_id': movimientos[0].subcuenta_id.cuenta_entidad_id.id
        })
        return rec

    def _get_movimientos(self):
        return self.env['account.move.line'].browse(self._context.get('active_ids'))

    @api.one
    def validar(self):
        movimientos = self._get_movimientos()

        if self.cambiar_tasa == True:
            for m in movimientos:
                if not m.interes_generado:
                    m.tasa_descubierto = self.tasa_de_interes
                    m.interes_fijo = False
                    m.subcuenta_id._actualizar_saldo_acumulado()

        if self.fijar_monto_de_interes == True:
            for m in movimientos:
                if not m.interes_generado:
                    m.monto_interes = self.monto_interes
                    m.interes_fijo = True
                    m.subcuenta_id._actualizar_saldo_acumulado()

        if self.crear_movimiento == True:
            if len(movimientos) > 1:
                raise ValidationError("Debe seleccionar solo un movimiento.")
            else:
                account_id = None
                if movimientos[0].subcuenta_id.tipo == 'activo':
                    account_id = movimientos[0].subcuenta_id.cuenta_entidad_id.account_cobrar_id.id
                else:
                    account_id = movimientos[0].subcuenta_id.cuenta_entidad_id.account_pagar_id.id

                # create move line
                # Creo un movimiento con debito y credito en cero para el calculo de intereses
                aml = {
                    'date': self.fecha_movimiento,
                    'account_id': account_id,
                    'name': 'Actualizacion de saldo e interes',
                    'partner_id': movimientos[0].subcuenta_id.cuenta_entidad_id.entidad_id.id,
                    'credit': 0,
                    'debit': 0,
                    'tasa_descubierto': movimientos[0].tasa_descubierto,
                    'subcuenta_id': movimientos[0].subcuenta_id.id,
                }

                # create move
                company_id = self.env['res.users'].browse(self.env.uid).company_id.id

                move_name = "Actualizacion de saldo e interes"
                move = self.env['account.move'].create({
                    'name': move_name,
                    'date': self.fecha_movimiento,
                    'journal_id': movimientos[0].journal_id.id,
                    'state':'draft',
                    'company_id': company_id,
                    'partner_id': movimientos[0].subcuenta_id.cuenta_entidad_id.entidad_id.id,
                    'line_ids': [(0,0,aml)],
                })
                #move.state = 'posted'
                #self.subcuenta_id._actualizar_saldo_acumulado()
                movimientos[0].subcuenta_id._actualizar_saldo_acumulado()

        if self.asentar_interes == True:
            flag_divisa = False
            if self.cuenta_entidad_id.currency_id.id != 20:
                flag_divisa = True
            for m in movimientos:

                if not m.interes_generado and m.subcuenta_id.tipo == 'activo' and m.monto_interes > 0:
                    account_id = m.subcuenta_id.cuenta_entidad_id.account_cobrar_id.id

                    if flag_divisa:
                        # create move line
                        # Creo asiento con los intereses generados en dicha fecha.
                        aml = {
                            'date': m.date,
                            'account_id': account_id,
                            'name': 'Interes generado',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'currency_id': self.cuenta_entidad_id.currency_id.id,
                            'amount_currency': m.monto_interes,
                            'debit': m.monto_interes * self.cuenta_entidad_id.currency_id.rate,
                        }

                        aml2 = {
                            'date': m.date,
                            'account_id': self.journal_intereses_id.default_debit_account_id.id,
                            'name': m.subcuenta_id.cuenta_entidad_id.entidad_id.name + ' - Interes generado',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'currency_id': self.cuenta_entidad_id.currency_id.id,
                            'amount_currency': -m.monto_interes,
                            'credit': m.monto_interes * self.cuenta_entidad_id.currency_id.rate,
                        }
                    else:
                        # create move line
                        # Creo asiento con los intereses generados en dicha fecha.
                        aml = {
                            'date': m.date,
                            'account_id': account_id,
                            'name': 'Interes generado',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'debit': m.monto_interes,
                        }

                        aml2 = {
                            'date': m.date,
                            'account_id': self.journal_intereses_id.default_debit_account_id.id,
                            'name': m.subcuenta_id.cuenta_entidad_id.entidad_id.name + ' - Interes generado',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'credit': m.monto_interes,
                        }

                    # create move
                    company_id = self.env['res.users'].browse(self.env.uid).company_id.id

                    move_name = "Intereses Generados"
                    move = self.env['account.move'].create({
                        'name': move_name,
                        'date': m.date,
                        'journal_id': self.journal_intereses_id.id,
                        'state':'draft',
                        'company_id': company_id,
                        'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                        'line_ids': [(0,0,aml), (0,0,aml2)],
                    })
                    #move.state = 'posted'
                    m.interes_generado = True
                    m.subcuenta_id._actualizar_saldo_acumulado()
                
                elif not m.interes_generado and m.subcuenta_id.tipo == 'pasivo' and m.monto_interes < 0:
                    account_id = m.subcuenta_id.cuenta_entidad_id.account_pagar_id.id

                    if flag_divisa:
                        # create move line
                        # Creo asiento con los intereses generados en dicha fecha.
                        aml = {
                            'date': m.date,
                            'account_id': account_id,
                            'name': 'Interes generado a pagar',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'currency_id': self.cuenta_entidad_id.currency_id.id,
                            'amount_currency': -abs(m.monto_interes),
                            'credit': abs(m.monto_interes) * self.cuenta_entidad_id.currency_id.rate,
                        }

                        aml2 = {
                            'date': m.date,
                            'account_id': self.journal_intereses_id.default_credit_account_id.id,
                            'name': m.subcuenta_id.cuenta_entidad_id.entidad_id.name + ' - Interes generado a pagar',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'currency_id': self.cuenta_entidad_id.currency_id.id,
                            'amount_currency': abs(m.monto_interes),
                            'debit': abs(m.monto_interes) * self.cuenta_entidad_id.currency_id.rate,
                        }
                    else:
                        # create move line
                        # Creo asiento con los intereses generados en dicha fecha.
                        aml = {
                            'date': m.date,
                            'account_id': account_id,
                            'name': 'Interes generado a pagar',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'credit': abs(m.monto_interes),
                        }

                        aml2 = {
                            'date': m.date,
                            'account_id': self.journal_intereses_id.default_credit_account_id.id,
                            'name': m.subcuenta_id.cuenta_entidad_id.entidad_id.name + ' - Interes generado a pagar',
                            'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                            'debit': abs(m.monto_interes),
                        }

                    # create move
                    company_id = self.env['res.users'].browse(self.env.uid).company_id.id

                    move_name = "Intereses Generados"
                    move = self.env['account.move'].create({
                        'name': move_name,
                        'date': m.date,
                        'journal_id': self.journal_intereses_id.id,
                        'state':'draft',
                        'company_id': company_id,
                        'partner_id': m.subcuenta_id.cuenta_entidad_id.entidad_id.id,
                        'line_ids': [(0,0,aml), (0,0,aml2)],
                    })
                    #move.state = 'posted'
                    m.interes_generado = True
                    m.subcuenta_id._actualizar_saldo_acumulado()

                else:
                    m.monto_interes = 0
                    m.interes_generado = True
                    m.subcuenta_id._actualizar_saldo_acumulado()

        if self.cambiar_subcuenta == True:
            for m in movimientos:
                if not m.interes_generado:
                    subcuenta_origen = m.subcuenta_id
                    m.subcuenta_id = self.subcuenta_destino_id
                    subcuenta_origen._actualizar_saldo_acumulado()
                    self.subcuenta_destino_id._actualizar_saldo_acumulado()

        self.state = 'confirmado'
        return {'type': 'ir.actions.act_window_close'}
