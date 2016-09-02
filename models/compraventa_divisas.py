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

class compraventa_divisas(osv.Model):
    _name = 'compraventa.divisas'
    _description = 'Operaciones con divisas'
    _order = 'id desc'
    _columns =  {
        'fecha': fields.date('Fecha', required=True),
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta'),
        'operacion': fields.selection([('compra', 'Compra'), ('venta', 'Venta')], string='Operacion'),
        'currency2_id': fields.many2one('compraventa.divisas.stock', 'Moneda'),
        'journal_moneda_secundaria_id': fields.many2one('account.journal', 'Diario moneda a comprar/vender', domain="[('type', 'in', ('cash', 'bank')), ('currency_id.id', '!=', 20)]"),
        'monto' : fields.float('Monto'),
        'pago_id': fields.many2one('compraventa.divisas.pago', 'Pago'),
        'move_id': fields.many2one('account.move', 'Asiento'),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmado', 'Confirmado'), ('pagado', 'Pagado'), ('asentado', 'Asentado')], string='Estado'),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'monto': 0,
        'state': 'borrador',
    }

    def confirmar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'confirmado'}, context=None)
        return True

    def _crear_asiento(self, ganancia):
        _logger.error("CREAR ASIENTO")
        fecha = self.fecha
        partner_id = self.cuenta_entidad_id.entidad_id.id
        operacion = self.operacion
        divisa_id = self.currency2_id.currency_id.id
        monto_en_divisas = self.monto
        caja_divisa_id = self.journal_moneda_secundaria_id.default_debit_account_id.id
        monto_en_efectivo = self.pago_id.monto_en_efectivo
        caja_efectivo_id = self.pago_id.journal_moneda_principal_id.default_debit_account_id.id
        diario_ganancia_id = self.pago_id.journal_ganancia_id

        line_ids = []
        debit = 0
        if ganancia > 0:
            _logger.error("GANANCIA > 0")
            gan = {
                'date': fecha,
                'account_id': diario_ganancia_id.default_credit_account_id.id,
                'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                'partner_id': partner_id,
                'credit': ganancia,
            }
            line_ids.append((0,0,gan))
            if operacion == 'compra':
                _logger.error("COMPRA")
                #COMPRA CON GANANCIA
                debit = monto_en_efectivo + ganancia
                # create move line
                # Registro el ingreso de divisas a su caja/cuenta
                aml = {
                    'date': fecha,
                    'account_id': caja_divisa_id,
                    'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'debit': debit,
                    'currency_id': divisa_id,
                    'amount_currency': monto_en_divisas,
                }
                line_ids.append((0,0,aml))

                # create move line
                # Registro la salida/ingreso de efectivo en pesos a su caja/cuenta
                aml2 = {
                    'date': fecha,
                    'account_id': caja_efectivo_id,
                    'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'credit': monto_en_efectivo,
                }
                line_ids.append((0,0,aml2))
            else:
                _logger.error("VENTA")
                credit = monto_en_efectivo - ganancia
                #VENTA CON GANANCIA
                # create move line
                # Registro el ingreso de divisas a su caja/cuenta
                aml = {
                    'date': fecha,
                    'account_id': caja_divisa_id,
                    'name': 'Venta - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'credit': credit,
                    'currency_id': divisa_id,
                    'amount_currency': -monto_en_divisas,
                }
                line_ids.append((0,0,aml))

                # create move line
                # Registro la salida/ingreso de efectivo en pesos a su caja/cuenta
                aml2 = {
                    'date': fecha,
                    'account_id': caja_efectivo_id,
                    'name': 'Venta - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'debit': monto_en_efectivo,
                }
                line_ids.append((0,0,aml2))
        else:
            _logger.error("GANANCIA < 0")
            gan = {
                'date': fecha,
                'account_id': diario_ganancia_id.default_debit_account_id.id,
                'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                'partner_id': partner_id,
                'debit': abs(ganancia),
            }
            line_ids.append((0,0,gan))
            if operacion == 'compra':
                _logger.error("COMPRA")
                #COMPRA CON PERDIDA
                debit = monto_en_efectivo - abs(ganancia)
                # create move line
                # Registro el ingreso de divisas a su caja/cuenta
                aml = {
                    'date': fecha,
                    'account_id': caja_divisa_id,
                    'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'debit': debit,
                    'currency_id': divisa_id,
                    'amount_currency': monto_en_divisas,
                }
                line_ids.append((0,0,aml))

                # create move line
                # Registro la salida/ingreso de efectivo en pesos a su caja/cuenta
                aml2 = {
                    'date': fecha,
                    'account_id': caja_efectivo_id,
                    'name': 'Compro - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'credit': monto_en_efectivo,
                    'amount_currency': 0,
                }
                line_ids.append((0,0,aml2))
                _logger.error("ganancia debit: %r", ganancia)
                _logger.error("debit: %r", debit)
                _logger.error("credit: %r", monto_en_efectivo)
                _logger.error("currency_id: %r", divisa_id)
                _logger.error("amount_currency: %r", monto_en_divisas)

            else:
                _logger.error("VENTA")
                credit = monto_en_efectivo + abs(ganancia)
                #VENTA CON PERDIDA
                # create move line
                # Registro el ingreso de divisas a su caja/cuenta
                aml = {
                    'date': fecha,
                    'account_id': caja_divisa_id,
                    'name': 'Venta - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'credit': credit,
                    'currency_id': divisa_id,
                    'amount_currency': -monto_en_divisas,
                }
                line_ids.append((0,0,aml))

                # create move line
                # Registro la salida/ingreso de efectivo en pesos a su caja/cuenta
                aml2 = {
                    'date': fecha,
                    'account_id': caja_efectivo_id,
                    'name': 'Venta - ' + str(monto_en_divisas) + ' x ' + str(self.pago_id.tipo_de_cambio),
                    'partner_id': partner_id,
                    'debit': monto_en_efectivo,
                }
                line_ids.append((0,0,aml2))

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        # create move
        move_name = "COMPRAVENTA/"+str(self.id)
        move = self.env['account.move'].create({
            'name': move_name,
            'date': self.fecha,
            'journal_id': self.pago_id.journal_moneda_principal_id.id,
            'state':'draft',
            'company_id': company_id,
            'partner_id': partner_id,
            'line_ids': line_ids,
        })
        move.state = 'posted'
        self.move_confirmacion_id = move.id


    @api.one
    def asentar(self):
        ganancia = self._actualizar_stock()
        self._crear_asiento(ganancia)
        self.state = 'asentado'
        return True

    def _actualizar_stock(self):
        ganancia = 0
        monto_stock = self.currency2_id.monto
        cotizacion_stock = self.currency2_id.cotizacion
        monto_actual = self.monto
        cotizacion_actual = self.pago_id.monto_en_efectivo / self.monto
        if self.operacion == 'venta':
            self.currency2_id.monto = monto_stock - monto_actual
            if monto_stock <= 0:
                self.currency2_id.cotizacion = (abs(monto_stock) * cotizacion_stock + monto_actual * cotizacion_actual) / (abs(monto_stock) + monto_actual)
                ganancia = 0
            elif monto_stock > 0:
                if monto_actual <= abs(monto_stock):
                    #No actualizamos la cotizacion, solo disminuye el monto en stock.
                    ganancia = monto_actual * (cotizacion_actual - cotizacion_stock)
                else:
                    #Sucede cuando el monto del stock es mayor a cero pero no alcanza a
                    #cubrir el monto de la venta.
                    #Por lo tanto sale el monto del stock
                    ganancia = monto_stock * (cotizacion_actual - cotizacion_stock)
                    self.currency2_id.cotizacion = cotizacion_actual
        elif self.operacion == 'compra':
            self.currency2_id.monto = monto_stock + monto_actual
            if monto_stock >= 0:
                self.currency2_id.cotizacion = (monto_stock * cotizacion_stock + monto_actual * cotizacion_actual) / (monto_stock + monto_actual)
                ganancia = 0
            elif monto_stock < 0:
                if monto_actual <= abs(monto_stock):
                    #No se modifica la cotizacion, solo sale el monto de venta.
                    ganancia = monto_actual * (cotizacion_stock - cotizacion_actual)
                else:
                    #Sucede cuando el stock es menos que cero pero la compra lo
                    #convierte en mayor a cero.
                    ganancia = monto_stock * (cotizacion_stock - cotizacion_actual)
                    self.currency2_id.cotizacion = cotizacion_actual
            if cotizacion_stock != self.currency2_id.cotizacion:
                _logger.error("Nueva cotizacion")
                historico_ids = []
                val = {
                        'monto': monto_stock,
                        'cotizacion': cotizacion_stock,
                        'compraventa_divisas_stock_id': self.currency2_id.id,
                        }

                historico_n = self.env['compraventa.divisas.stock.historico'].create(val)
                for h in self.currency2_id.historico_ids:
                    historico_ids.append(h.id)
                    _logger.error("historicos: %r", h.cotizacion)
                historico_ids.append(historico_n.id)
                self.currency2_id.historico_ids = historico_ids


        return ganancia


class compraventa_divisas_pago(osv.Model):
    _name = 'compraventa.divisas.pago'
    _description = 'Pago compraventa'
    _columns =  {
        'fecha': fields.date('Fecha', required=True),
        'operacion': fields.selection([('compra', 'Compra'), ('venta', 'Venta')], string='Operacion'),
        'journal_moneda_principal_id': fields.many2one('account.journal', 'Diario del pago/cobro en pesos', domain="[('type', 'in', ('cash', 'bank'))]"),
        'state': fields.selection([('borrador', 'Borrador'), ('pagado', 'Pagado')], string='Estado'),
        'tipo_de_cambio' : fields.float('Tipo de cambio'),
        'monto_en_efectivo' : fields.float('Monto en efectivo'),
        'move_id': fields.many2one('account.move', 'Asiento'),
        'journal_ganancia_id': fields.many2one('account.journal', 'Diario de ganancias por compra/venta', domain="[('type', '=', 'sale')]"),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
    }

    @api.model
    def default_get(self, fields):
        rec = super(compraventa_divisas_pago, self).default_get(fields)
        context = dict(self._context or {})
        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        # Checks on context parameters
#        if not active_model or not active_ids:
#            raise UserError(_("Programmation error: wizard action executed without active_model or active_ids in context."))
#        if active_model != None and active_ids != None and active_id != None:
        compraventa_id = self.env[active_model].browse(active_id)[0]
            #if cheque.state != 'depositado' and cheque.state != 'enpago':
            #    raise UserError(_("No puedes procesar un rechazo si no fue 'Depositado' o dado 'En Pago' previamente."))

        rec.update({
            'fecha': compraventa_id.fecha,
            'operacion': compraventa_id.operacion,
        })
        return rec

        
    def _get_compraventa(self):
        return self.env['compraventa.divisas'].browse(self._context.get('active_id'))[0]

    @api.one
    def validar_pago(self):
        compraventa_id = self._get_compraventa()
        if compraventa_id.monto * self.tipo_de_cambio != self.monto_en_efectivo:
            raise ValidationError("Controlar el monto de la divisa, tipo de cambio y el monto en efectivo.")
        else:
            self.state = 'pagado'
            compraventa_id.state = 'pagado'
            compraventa_id.pago_id = self.id
            #ganancia = compraventa_id._actualizar_stock()
            #_logger.error("ganancia: %r", ganancia)
        return {'type': 'ir.actions.act_window_close'}

class compraventa_divisas_stock(osv.Model):
    _name = 'compraventa.divisas.stock'
    _description = 'Operaciones con divisas'
    _rec_name = 'display_name'
    _columns =  {
        'display_name': fields.char("Moneda", compute='_compute_display_name', readonly=True),
        'currency_id': fields.many2one('res.currency', 'Moneda', domain="[('active', '=', True)]", required=True),
        'monto' : fields.float('Monto', required=True),
        'cotizacion' : fields.float('Cotizacion', required=True),
        'historico_ids': fields.one2many('compraventa.divisas.stock.historico', 'compraventa_divisas_stock_id', 'Historico'),
    }

    _defaults = {
        'monto': 0,
    }
    _sql_constraints = [
            ('id_uniq', 'unique (currency_id)', "Esta moneda ya existe!"),
    ]

    @api.one
    @api.depends('currency_id')
    def _compute_display_name(self):
        if self.currency_id:
            self.display_name = self.currency_id.name

class compraventa_divisas_stock_historico(osv.Model):
    _name = 'compraventa.divisas.stock.historico'
    _description = 'Historial divisas'
    _order = 'id desc'
    _columns =  {
        'fecha': fields.date("Fecha"),
        'monto' : fields.float('Monto', required=True),
        'cotizacion' : fields.float('Cotizacion', required=True),
        'compraventa_divisas_stock_id': fields.many2one('compraventa.divisas.stock', 'Moneda'),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
    }