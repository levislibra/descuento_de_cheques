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
    _columns =  {
        'fecha': fields.date('Fecha', required=True),
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta'),
        'operacion': fields.selection([('compra', 'Compra'), ('venta', 'Venta')], string='Operacion'),
        'currency2_id': fields.many2one('compraventa.divisas.stock', 'Moneda'),
        'journal_moneda_secundaria_id': fields.many2one('account.journal', 'Diario moneda a comprar/vender', domain="[('type', 'in', ('cash', 'bank')), ('currency_id.id', '!=', 20)]"),
        'monto' : fields.float('Monto'),
        'pago_id': fields.many2one('compraventa.divisas.pago', 'Pago'),
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

    @api.one
    def asentar(self):
        self._actualizar_stock()
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
