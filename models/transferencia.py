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
import subcuenta
_logger = logging.getLogger(__name__)
#       _logger.error("date now : %r", date_now)

# Add a new floats fields and date object cheques.de.terceros
class cheques_de_terceros(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'
    _name = 'cheques.de.terceros'
    _description = 'opciones extras de cheques para calculo del descuento'

    _columns = {
        'transferencia_enviar_id': fields.many2one('transferencia', 'Transferencia enviar id'),
        'transferencia_recibir_id': fields.many2one('transferencia', 'Transferencia recibir id'),
    }

class account_move_line(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'account.move.line'
    _name = 'account.move.line'
    _description = 'account.move.line'

    _columns = {
        'transferencia_id': fields.many2one('transferencia', 'Transferencia ID'),
    }

class transferencia(osv.Model):
    _name = 'transferencia'
    _description = 'trensferencias entre cuentas'

    _columns = {
        'fecha': fields.date('Fecha', required=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmada', 'Confirmada'), ('registrada', 'Registrada'), ('cancelada', 'Cancelada')], string='Estado', readonly=True),
        'tipo_de_pago': fields.selection([('enviarDinero', 'Pago/Enviar dinero/Deposito bancario'), ('recibirDinero', 'Cobro/Recibir dinero'), ('transferenciaEntidad', 'Transferencia entre subcuentas'), ('transferenciaContable', 'Transferencia contable')], string='Tipo de pago', required=True),
        'journal_id': fields.many2one('account.journal', 'Diario', required=True),
        'move_id': fields.many2one('account.move', 'Asiento', readonly=True),
        'state_move_id': fields.char('Estado', readonly=True),
        'move_line_ids': fields.one2many('account.move.line', 'transferencia_id', related='move_id.line_ids', readonly=True, store=False),

        'entidad_id': fields.many2one('res.partner', 'Entidad'),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta'),
        'entidad2_id': fields.many2one('res.partner', 'Entidad Receptora', help="Receptor de la transferencia"),
        'subcuenta2_id': fields.many2one('subcuenta', 'Subcuenta Receptora'),

        'cuenta_id': fields.many2one('account.account', 'Cuenta'),
        'cuenta2_id': fields.many2one('account.account', 'Cuenta  Receptora', help="Cuenta Receptora de la transferencia"),

        'efectivo': fields.boolean('Efectivo'),
        'monto_efectivo': fields.float('Monto efectivo'),
        'monto': fields.float('Monto'),
        'cheques': fields.boolean('Cheques'),
        'enviar_cheques_ids': fields.one2many('cheques.de.terceros', 'transferencia_enviar_id', 'Cheques a enviar'),
        'recibir_cheques_ids': fields.one2many('cheques.de.terceros', 'transferencia_recibir_id', 'Cheques a recibir'),
        'deposito_bancario': fields.boolean('Deposito bancario'),
        'gastos': fields.boolean('Aplicar Gastos'),
        'monto_gasto': fields.float('Monto del gasto'),
        'porcentaje_gasto': fields.float('Porcentaje de gasto sobre cheques'),
        'cuenta_gastos_id': fields.many2one('account.account', 'Cuenta gastos'),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
        'tipo_de_pago': 'enviarDinero',
        'efectivo': False,
        'cheques': False,
        'aplicar_porcentaje': 'cheques',
        'deposito_bancario': False,
    }

    @api.onchange('tipo_de_pago')
    def _reiniciar_subcuenta_id(self):
        _logger.error("tipo_de_pago onchange")
        self.journal_id = False
        self.deposito_bancario = False
        self.entidad_id = False
        self.subcuenta_id = False
        self.entidad2_id = False
        self.subcuenta2_id = False
        self.cuenta_id = False
        self.cuenta2_id = False
        self.efectivo = False
        self.monto_efectivo = False
        self.monto = False
        self.cheques = False
        self.enviar_cheques_ids = False
        self.recibir_cheques_ids = False
        self.gastos = False
        self.monto_gasto = False
        self.porcentaje_gasto = False
        self.cuenta_gastos_id = False

    @api.onchange('entidad_id')
    def _reiniciar_subcuenta_id(self):
        _logger.error("subcuenta1")
        if self.entidad_id:
            self.subcuenta_id = False

    @api.onchange('entidad2_id')
    def _reiniciar_subcuenta2_id(self):
        _logger.error("subcuenta2")
        if self.entidad2_id:
            self.subcuenta2_id = False

    def editar(self, cr, uid, ids, context=None):
        _logger.error("self2: %r", self)
        self.write(cr, uid, ids, {'state':'borrador'}, context=None)
        return True

    @api.multi
    def confirmar(self, cr):
        self.state = 'confirmada'
        company_id = self.env['res.users'].browse(self.env.uid).company_id.id

        if self.tipo_de_pago == 'enviarDinero':
            #list of move line
            line_ids = []
            monto_en_cheques = 0
            if self.deposito_bancario:
                account_id = self.cuenta_id
                subcuenta_id = False
                partner_id = False
            else:
                account_id = self.entidad_id.property_account_receivable_id
                subcuenta_id = self.subcuenta_id.id
                partner_id = self.entidad_id.id

            _logger.error("enviarDinero")
            if self.efectivo == True:
                _logger.error("efectivo == True")
                if self.monto_efectivo > 0:
                    _logger.error("efectivo > 0")
                    # create move line
                    # Registro el monto en efectivo que sale de caja
                    aml = {
                        'date': self.fecha,
                        'account_id': self.journal_id.cuenta_caja_id.id,
                        'name': 'Pago - Enviar dinero - '+ self.entidad_id.name,
                        'partner_id': partner_id,
                        'credit': self.monto_efectivo,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de efectivo entregado a la entidad o depositado
                    aml2 = {
                        'date': self.fecha,
                        'account_id': account_id.id,
                        'name': 'Efectivo - '+ self.journal_id.cuenta_caja_id.name,
                        'partner_id': partner_id,
                        'debit': self.monto_efectivo,
                        'subcuenta_id': subcuenta_id,
                    }
                    line_ids.append((0,0,aml2))
            if self.cheques == True:
                for cheque in self.enviar_cheques_ids:
                    _logger.error("cheque: %r", cheque.importe)
                    monto_en_cheques += cheque.importe

                    # create move line
                    # Monto y detalle del cheque en la cuenta receptora o cuenta donde se deposito
                    amlfor = {
                        'date': self.fecha,
                        'account_id': account_id.id,
                        'name': 'banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                        'partner_id': partner_id,
                        'debit': cheque.importe,
                        'subcuenta_id': subcuenta_id,
                    }
                    line_ids.append((0,0,amlfor))

                    #obtengo la procedencia del cheque (account.account)
                    account_cheques_id = False
                    _logger.error("cheque.liquidacion_id: %r", cheque.liquidacion_id.id)
                    _logger.error("cheque.transferencia_recibir_id: %r", cheque.transferencia_recibir_id.id)

                    if cheque.liquidacion_id.id != False:
                        account_cheques_id = cheque.liquidacion_id.journal_id.cuenta_cheques_id.id
                    else:
                        if cheque.transferencia_recibir_id.id != False:
                            account_cheques_id = cheque.transferencia_recibir_id.journal_id.cuenta_cheques_id.id

                    _logger.error("account_cheque: %r", account_cheques_id)
                    if account_cheques_id == False:
                        raise ValidationError("Hay cheques que no pertenecen a una liquidacion o un cobro.")
                    else:
                        # create move line
                        # Monto y detalle del cheque que sale
                        amlfor2 = {
                            'date': self.fecha,
                            'account_id': account_cheques_id,
                            'name': 'banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                            'partner_id': partner_id,
                            'credit': cheque.importe,
                        }
                        line_ids.append((0,0,amlfor2))

            if self.gastos == True:
                _logger.error("gastos == True")
                if self.monto_gasto > 0:
                    _logger.error("monto_gasto > 0")
                    # create move line
                    # Registro el monto de gasto como egreso
                    aml = {
                        'date': self.fecha,
                        'account_id': self.cuenta_gastos_id.id,
                        'name': 'Gastos - Enviar dinero - '+ account_id.name,
                        'partner_id': partner_id,
                        'debit': self.monto_gasto,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de gasto a favor de la entidad o cuenta
                    aml2 = {
                        'date': self.fecha,
                        'account_id': account_id.id,
                        'name': 'Gasto - '+ self.cuenta_gastos_id.name,
                        'partner_id': partner_id,
                        'credit': self.monto_gasto,
                        'subcuenta_id': subcuenta_id,
                    }
                    line_ids.append((0,0,aml2))
                if self.porcentaje_gasto > 0 and monto_en_cheques > 0:
                    _logger.error("procentaje > 0")
                    # create move line
                    # Registro el monto de gasto como egreso
                    monto_porcentaje_gasto = monto_en_cheques*self.porcentaje_gasto/100
                    aml = {
                        'date': self.fecha,
                        'account_id': self.cuenta_gastos_id.id,
                        'name': 'Gastos - Enviar dinero/deposito - '+ account_id.name+' '+str(self.porcentaje_gasto)+'% sobre '+str(monto_en_cheques),
                        'partner_id': partner_id,
                        'debit': monto_porcentaje_gasto,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de gasto a favor de la entidad o cuenta
                    aml2 = {
                        'date': self.fecha,
                        'account_id': account_id.id,
                        'name': 'Gasto - '+ self.cuenta_gastos_id.name+' '+str(self.porcentaje_gasto)+'% sobre '+str(monto_en_cheques),
                        'partner_id': partner_id,
                        'credit': monto_porcentaje_gasto,
                        'subcuenta_id': subcuenta_id,
                    }
                    line_ids.append((0,0,aml2))
            # create move
            move_name = 'Pago - Enviar Dinero/'+str(self.id)
            move = self.env['account.move'].create({
                'name': move_name,
                'ref': move_name,
                'date': self.fecha,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': partner_id,
                'line_ids': line_ids,
            })
            #move.state = 'posted'
            self.move_id = move.id
            self.state_move_id = move.state
            self.subcuenta_id._actualizar_saldo_acumulado()


        if self.tipo_de_pago == 'recibirDinero':
            #list of move line
            line_ids = []
            _logger.error("recibirDinero")
            if self.efectivo == True:
                _logger.error("efectivo == True")
                if self.monto_efectivo > 0:
                    _logger.error("efectivo > 0")
                    # create move line
                    # Registro el monto en efectivo que ingresa a caja
                    aml = {
                        'date': self.fecha,
                        'account_id': self.journal_id.cuenta_caja_id.id,
                        'name': 'Cobro - Recibir dinero - '+ self.entidad_id.name,
                        'partner_id': self.entidad_id.id,
                        'debit': self.monto_efectivo,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de efectivo entregado por la entidad
                    aml2 = {
                        'date': self.fecha,
                        'account_id': self.entidad_id.property_account_receivable_id.id,
                        'name': 'Efectivo - '+ self.journal_id.cuenta_caja_id.name,
                        'partner_id': self.entidad_id.id,
                        'credit': self.monto_efectivo,
                        'subcuenta_id': self.subcuenta_id.id,
                    }
                    line_ids.append((0,0,aml2))
            if self.cheques == True:
                for cheque in self.recibir_cheques_ids:
                    # create move line
                    # Monto y detalle del cheque en la cuenta emisora
                    amlfor = {
                        'date': self.fecha,
                        'account_id': self.entidad_id.property_account_receivable_id.id,
                        'name': 'Banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                        'partner_id': self.entidad_id.id,
                        'credit': cheque.importe,
                        'subcuenta_id': self.subcuenta_id.id,
                    }
                    line_ids.append((0,0,amlfor))

                    # create move line
                    # Monto y detalle del cheque que sale
                    amlfor2 = {
                        'date': self.fecha,
                        'account_id': self.journal_id.cuenta_cheques_id.id,
                        'name': 'Banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                        'partner_id': self.entidad_id.id,
                        'debit': cheque.importe,
                    }
                    line_ids.append((0,0,amlfor2))

            # create move
            move_name = 'Cobro - Recibir Dinero/'+str(self.id)
            move = self.env['account.move'].create({
                'name': move_name,
                'ref': move_name,
                'date': self.fecha,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.entidad_id.id,
                'line_ids': line_ids,
            })
            #move.state = 'posted'
            self.move_id = move.id
            self.state_move_id = move.state
            self.subcuenta_id._actualizar_saldo_acumulado()



        if self.tipo_de_pago == 'transferenciaEntidad':
            pass


        if self.tipo_de_pago == 'transferenciaContable':
            pass

    def registrar(self, cr, uid, ids, context=None):
        _logger.error("self1: %r", self)
        self.write(cr, uid, ids, {'state':'registrada'}, context=None)
        return True

    def cancelar(self, cr, uid, ids, context=None):
        _logger.error("self2: %r", self)
        self.write(cr, uid, ids, {'state':'cancelada'}, context=None)
        return True