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
        'move_id': fields.many2one('account.move', 'Asiento', readonly=True),
        'state_move_id': fields.char('Estado', readonly=True),
        'move_line_ids': fields.one2many('account.move.line', 'transferencia_id', related='move_id.line_ids', readonly=True, store=False),

        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Entidad'),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta'),
        'cuenta_entidad2_id': fields.many2one('cuenta.entidad', 'Entidad Receptora', help="Receptor de la transferencia"),
        'subcuenta2_id': fields.many2one('subcuenta', 'Subcuenta Receptora'),

        'cuenta_id': fields.many2one('account.account', 'Cuenta'),
        'cuenta2_id': fields.many2one('account.account', 'Cuenta  Receptora', help="Cuenta Receptora de la transferencia"),

        'journal_id': fields.many2one('account.journal', 'Metodo de pago/cobro'),
        'efectivo': fields.boolean('Efectivo'),
        'monto_efectivo': fields.float('Monto efectivo'),
        'monto': fields.float('Monto'),
        'cheques': fields.boolean('Cheques'),
        'journal_recibir_cheques_id': fields.many2one('account.journal', 'Cartera de cheques'),
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
    def _reiniciar_formulario(self):
        _logger.error("tipo_de_pago onchange")
        self.journal_id = False
        self.deposito_bancario = False
        self.cuenta_entidad_id = False
        self.subcuenta_id = False
        self.cuenta_entidad2_id = False
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

    @api.onchange('cuenta_entidad_id')
    def _reiniciar_subcuenta_id(self):
        _logger.error("subcuenta1")
        if self.cuenta_entidad_id:
            self.subcuenta_id = False

    @api.onchange('cuenta_entidad2_id')
    def _reiniciar_subcuenta2_id(self):
        _logger.error("subcuenta2")
        if self.cuenta_entidad2_id:
            self.subcuenta2_id = False

    def editar(self, cr, uid, ids, context=None):
        _logger.error("self2: %r", self)
        self.write(cr, uid, ids, {'state':'borrador'}, context=None)
        return True

    @api.multi
    def confirmar(self, cr):
        self.state = 'confirmada'
        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        journal_asiento_id = None

        if self.tipo_de_pago == 'enviarDinero':
            #list of move line
            line_ids = []
            monto_en_cheques = 0
            if self.deposito_bancario:
                account_id = self.cuenta_id
                subcuenta_id = False
                partner_id = False
                cheque_state = 'depositado'
                boleta_deposito = self.cuenta_id.name
            else:
                if self.subcuenta_id.tipo == 'activo':
                    account_id = self.cuenta_entidad_id.account_cobrar_id
                else:
                    account_id = self.cuenta_entidad_id.account_pagar_id
                subcuenta_id = self.subcuenta_id.id
                partner_id = self.cuenta_entidad_id.entidad_id.id
                cheque_state = 'enpago'
                boleta_deposito = self.cuenta_entidad_id.display_name + '/' + self.subcuenta_id.name

            if self.efectivo == True:
                _logger.error("efectivo == True")
                if self.monto_efectivo > 0:
                    _logger.error("efectivo > 0")
                    # create move line
                    # Registro el monto en efectivo que sale de caja
                    _logger.error("account_id 1: %r", self.journal_id.default_debit_account_id.id)
                    aml = {
                        'date': self.fecha,
                        'account_id': self.journal_id.default_debit_account_id.id,
                        'name': 'Pago - Enviar dinero - '+ self.cuenta_entidad_id.display_name,
                        'partner_id': partner_id,
                        'credit': self.monto_efectivo,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de efectivo entregado a la entidad o depositado
                    _logger.error("account_id 2: %r", account_id.id)
                    aml2 = {
                        'date': self.fecha,
                        'account_id': account_id.id,
                        'name': 'Efectivo - '+ self.journal_id.default_debit_account_id.name,
                        'partner_id': partner_id,
                        'debit': self.monto_efectivo,
                        'subcuenta_id': subcuenta_id,
                    }
                    line_ids.append((0,0,aml2))
                    journal_asiento_id = self.journal_id.id
            if self.cheques == True:
                for cheque in self.enviar_cheques_ids:
                    monto_en_cheques += cheque.importe
                    cheque.state = cheque_state
                    cheque.fecha_deposito = self.fecha
                    cheque.account_destino_id = account_id.id
                    cheque.boleta_deposito = boleta_deposito
                    cheque.cuenta_entidad_destino_id = self.cuenta_entidad_id.id
                    cheque.subcuenta_destino_id = self.subcuenta_id.id

                    # create move line
                    # Monto y detalle del cheque en la cuenta receptora o cuenta donde se deposito
                    _logger.error("account_id 3: %r", account_id.id)
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

                    account_cheques_id = cheque.journal_id.default_debit_account_id.id
                    journal_asiento_id = cheque.journal_id.id

                    if account_cheques_id == False:
                        raise ValidationError("Hay cheques que no pertenecen a una liquidacion o un cobro.")
                    else:
                        # create move line
                        # Monto y detalle del cheque que sale
                        _logger.error("account_id 4: %r", account_cheques_id)
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
                'journal_id': journal_asiento_id,
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
            if self.subcuenta_id.tipo == 'activo':
                account_id = self.cuenta_entidad_id.account_cobrar_id.id
            else:
                account_id = self.cuenta_entidad_id.account_pagar_id.id


            if self.efectivo == True:
                if self.monto_efectivo > 0:
                    # create move line
                    # Registro el monto en efectivo que ingresa a caja
                    aml = {
                        'date': self.fecha,
                        'account_id': self.journal_id.default_debit_account_id.id,
                        'name': 'Cobro - Recibir dinero - '+ self.cuenta_entidad_id.display_name,
                        'partner_id': self.cuenta_entidad_id.entidad_id.id,
                        'debit': self.monto_efectivo,
                    }
                    line_ids.append((0,0,aml))

                    # create move line
                    # Registro el monto de efectivo entregado por la entidad
                    aml2 = {
                        'date': self.fecha,
                        'account_id': account_id,
                        'name': 'Efectivo - '+ self.journal_id.name,
                        'partner_id': self.cuenta_entidad_id.entidad_id.id,
                        'credit': self.monto_efectivo,
                        'subcuenta_id': self.subcuenta_id.id,
                    }
                    line_ids.append((0,0,aml2))
            if self.cheques == True:
                _logger.error("Recibir cheques!!!")
                _logger.error("account_id: %r", account_id)
                for cheque in self.recibir_cheques_ids:

                    cheque.state = 'draft'
                    cheque.journal_id = self.journal_recibir_cheques_id.id
                    cheque.cuenta_entidad_id = self.cuenta_entidad_id.id
                    cheque.subcuenta_id = self.subcuenta_id.id

                    # create move line
                    # Monto y detalle del cheque en la cuenta emisora
                    amlfor = {
                        'date': self.fecha,
                        'account_id': account_id,
                        'name': 'Banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                        'partner_id': self.cuenta_entidad_id.entidad_id.id,
                        'credit': cheque.importe,
                        'subcuenta_id': self.subcuenta_id.id,
                    }
                    line_ids.append((0,0,amlfor))

                    # create move line
                    # Monto y detalle del cheque que ingresa
                    amlfor2 = {
                        'date': self.fecha,
                        'account_id': self.journal_recibir_cheques_id.default_debit_account_id.id,
                        'name': 'Banco '+ cheque.banco_id.name+' Nro '+cheque.name,
                        'partner_id': self.cuenta_entidad_id.entidad_id.id,
                        'debit': cheque.importe,
                    }
                    line_ids.append((0,0,amlfor2))

            journal_asiento_id = self.journal_id.id or self.journal_recibir_cheques_id.id
            _logger.error("jorunal_id!!:: %r", journal_asiento_id)
            # create move
            move_name = 'Cobro - Recibir Dinero/'+str(self.id)
            move = self.env['account.move'].create({
                'name': move_name,
                'ref': move_name,
                'date': self.fecha,
                'journal_id': journal_asiento_id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'line_ids': line_ids,
            })
            #move.state = 'posted'
            self.move_id = move.id
            self.state_move_id = move.state
            self.subcuenta_id._actualizar_saldo_acumulado()



        if self.tipo_de_pago == 'transferenciaEntidad':
            _logger.error("transferenciaEntidad!!!")
            #inicializacion
            line_ids = []

            if self.subcuenta_id.tipo == 'activo':
                account_id = self.cuenta_entidad_id.account_cobrar_id.id
            else:
                account_id = self.cuenta_entidad_id.account_pagar_id.id
            # create move line
            # Registro el monto en efectivo que sale de la cuenta emisora
            aml = {
                'date': self.fecha,
                'account_id': account_id,
                'name': 'Transferencia - destino: '+ self.cuenta_entidad2_id.display_name + ' subcuenta: '+self.subcuenta2_id.name,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'debit': self.monto,
                'subcuenta_id': self.subcuenta_id.id,
            }
            line_ids.append((0,0,aml))
            _logger.error("aml: %r", aml)


            if self.subcuenta2_id.tipo == 'activo':
                account2_id = self.cuenta_entidad2_id.account_cobrar_id.id
            else:
                account2_id = self.cuenta_entidad2_id.account_pagar_id.id

            # create move line
            # Registro el monto de efectivo entregado a la entidad receptora
            aml2 = {
                'date': self.fecha,
                'account_id': account2_id,
                'name': 'Transferencia - origen: '+ self.cuenta_entidad_id.entidad_id.display_name + ' subcuenta: '+self.subcuenta_id.name,
                'partner_id': self.cuenta_entidad2_id.entidad_id.id,
                'credit': self.monto,
                'subcuenta_id': self.subcuenta2_id.id,
            }
            line_ids.append((0,0,aml2))
            _logger.error("aml: %r", aml2)

            # create move
            move_name = 'Transferencia - Entre entidades/'+str(self.id)
            move = self.env['account.move'].create({
                'name': move_name,
                'ref': move_name,
                'date': self.fecha,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'line_ids': line_ids,
            })
            _logger.error("move: %r", move)
            #move.state = 'posted'
            self.move_id = move.id
            self.state_move_id = move.state
            self.subcuenta_id._actualizar_saldo_acumulado()
            self.subcuenta2_id._actualizar_saldo_acumulado()



        if self.tipo_de_pago == 'transferenciaContable':
            _logger.error("transferenciaContable!!!")
            #inicializacion
            line_ids = []
            # create move line
            # Registro el monto en efectivo que sale de caja
            aml = {
                'date': self.fecha,
                'account_id': self.cuenta_id.id,
                'name': 'Transferencia - destino: '+ self.cuenta2_id.name,
                'credit': self.monto,
            }
            line_ids.append((0,0,aml))
            _logger.error("aml: %r", aml)

            # create move line
            # Registro el monto de efectivo entregado a la entidad o depositado
            aml2 = {
                'date': self.fecha,
                'account_id': self.cuenta2_id.id,
                'name': 'Transferencia - origen: '+ self.cuenta_id.name,
                'debit': self.monto,
            }
            line_ids.append((0,0,aml2))
            _logger.error("aml: %r", aml2)

            # create move
            move_name = 'Transferencia - Contable/'+str(self.id)
            move = self.env['account.move'].create({
                'name': move_name,
                'ref': move_name,
                'date': self.fecha,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'line_ids': line_ids,
            })
            _logger.error("move: %r", move)
            #move.state = 'posted'
            self.move_id = move.id
            self.state_move_id = move.state

    @api.multi
    def registrar(self, cr):
        _logger.error("registraar: %r", self)
        self.state = 'registrada'
        self.move_id.state = 'posted'
        self.state_move_id = 'posted'
        for cheque in self.recibir_cheques_ids:
            cheque.state = 'en_cartera'
        return True

    @api.multi
    def cancelar(self, cr):
        _logger.error("cancelar: %r", self)
        self.state = 'cancelada'
        self.move_id.unlink()
        self.state_move_id = 'deleted'
        for cheque in self.recibir_cheques_ids:
            cheque.unlink()
        for cheque in self.enviar_cheques_ids:
            cheque.state = 'en_cartera'
        return True