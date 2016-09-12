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
import plazo_fijo
_logger = logging.getLogger(__name__)
#       _logger.error("date now : %r", date_now)

class cuenta_entidad(osv.Model):
    _name = 'cuenta.entidad'
    _description = 'Es la cuenta que agrupa todos los movimientos de una entidad (cliente/proveedor).'
    _rec_name = "display_name"

    _columns = {
        'fecha': fields.date('Fecha', required=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmada', 'Confirmada')], string='Estado', readonly=True),
        'active': fields.boolean("Activa"),
        'display_name': fields.char("Nombre", compute='_compute_display_name', readonly=True),

        'entidad_id': fields.many2one('res.partner', 'Entidad', required=True),
        'currency_id': fields.many2one('res.currency', 'Moneda', domain="[('active', '=', True)]", required=True),
        'account_cobrar_id': fields.many2one('account.account', 'Cuentas a cobrar', domain="[('internal_type','=', 'receivable'), ('deprecated', '=', False)]", required=True),
        'account_pagar_id': fields.many2one('account.account', 'Cuentas a pagar', domain="[('internal_type','=', 'payable'), ('deprecated', '=', False)]", required=True),
        'descuento_de_cheques_ids': fields.one2many("descuento.de.cheques", "cuenta_entidad_id", "Descuentos", readonly=True),
        'subcuentas_ids': fields.one2many('subcuenta', 'cuenta_entidad_id', 'Subcuentas'),
        'plazos_fijos_ids': fields.one2many('plazo.fijo', 'cuenta_entidad_id', 'Plazos Fijos'),

    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
        'active': True,
    }

    @api.one
    @api.depends('entidad_id')
    def _compute_display_name(self):
        if self.entidad_id:
            self.display_name = 'Cuenta ' + self.entidad_id.name
            self.account_cobrar_id = self.entidad_id.property_account_receivable_id.id
            self.account_pagar_id = self.entidad_id.property_account_payable_id.id
            if self.currency_id:
                company_currency_id = self.env['res.users'].browse(self.env.uid).currency_id.id
                cuenta_currency_id = self.currency_id.id
                if company_currency_id != cuenta_currency_id:
                    self.display_name = self.display_name + ' (' + self.currency_id.name + ')'

    @api.onchange('currency_id')
    def _set_cuentas(self):
        company_currency_id = self.env['res.users'].browse(self.env.uid).currency_id.id
        cuenta_currency_id = self.currency_id.id
        if company_currency_id != cuenta_currency_id:
            self.account_cobrar_id = False
            self.account_pagar_id = False
            if self.display_name:
                self.display_name = 'Cuenta ' + self.entidad_id.name + ' (' + self.currency_id.name + ')'
        else:
            if self.display_name:
                self.display_name = 'Cuenta ' + self.entidad_id.name
    
    @api.multi
    def confirmar(self, cr):
        company_currency_id = self.env['res.users'].browse(self.env.uid).currency_id.id
        cuenta_currency_id = self.currency_id.id
        
        cobrar_currency_id = self.account_cobrar_id.currency_id.id
        flag_account_cobrar = not (company_currency_id != cuenta_currency_id and (cobrar_currency_id != False and cobrar_currency_id == cuenta_currency_id))
        flag_account_cobrar = flag_account_cobrar and not (company_currency_id == cuenta_currency_id and (cobrar_currency_id == False or cobrar_currency_id == cuenta_currency_id))

        pagar_currency_id = self.account_pagar_id.currency_id.id
        flag_account_pagar = not (company_currency_id != cuenta_currency_id and (pagar_currency_id != False and pagar_currency_id == cuenta_currency_id))
        flag_account_pagar = flag_account_pagar and not (company_currency_id == cuenta_currency_id and (pagar_currency_id == False or pagar_currency_id == cuenta_currency_id))

        if flag_account_cobrar:
            raise UserError(_("Comprobar Cuentas por cobrar, difiere Moneda."))
        elif flag_account_pagar:
            raise UserError(_("Comprobar Cuentas por pagar, difiere Moneda."))
        else:
            self.state = 'confirmada'
        return True

    def editar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'borrador'}, context=None)
        return True

    @api.multi
    def cancelar(self, cr):
        self.state = 'cancelada'
        self.move_id.unlink()
        self.state_move_id = 'deleted'
        for cheque in self.recibir_cheques_ids:
            cheque.unlink()
        for cheque in self.enviar_cheques_ids:
            cheque.state = 'en_cartera'
        return True
