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

class balance(osv.Model):
    _inherit = 'account.account'
    #_name = 'balance'
    _description = 'balances y saldos de cuentas contables'
    _columns =  {
        'saldo' : fields.float('Saldo', readonly=True),
        'move_line_ids': fields.one2many('account.move.line', 'account_id', 'Apuntes'),
    }

    _defaults = {
        'saldo': 0,
    }

    @api.multi
    def actsaldo(self, cr):
        apunte_previo = None
        apuntes_ids = self.move_line_ids
        count = len(apuntes_ids)
        company_currency_id = self.env['res.users'].browse(self.env.uid).currency_id.id
        currency_default = self.currency_id.id == False or self.currency_id.id == company_currency_id
        self.saldo = 0
        i = 1   
        while i <= count:
            apunte = apuntes_ids[count-i]
            if currency_default:
                self.saldo += apunte.debit - apunte.credit
            else:
                self.saldo += apunte.amount_currency
            if apunte_previo != None:
                if currency_default:
                    apunte.sub_saldo = apunte.debit - apunte.credit + apunte_previo.sub_saldo
                    apunte.saldo = apunte.debit - apunte.credit + apunte_previo.saldo
                else:
                    apunte.sub_saldo = apunte.amount_currency + apunte_previo.sub_saldo
                    apunte.saldo = apunte.amount_currency + apunte_previo.saldo
            else:
                if currency_default:
                    apunte.sub_saldo = apunte.debit - apunte.credit
                    apunte.saldo = apunte.debit - apunte.credit
                else:
                    apunte.sub_saldo = apunte.amount_currency
                    apunte.saldo = apunte.amount_currency
            apunte_previo = apunte
            i = i + 1
    
class balance_view(osv.Model):
    _name = 'balance.view'
    _description = 'balances y saldos de cuentas contables'

    def actualizar_cuentas(self,cr,uid,ids,context={}):
        cuentas_obj = self.pool.get('account.account')
        cuentas_obj_ids = cuentas_obj.search(cr, uid, [])
        dummy, view_id = self.pool.get('ir.model.data').get_object_reference(cr, uid, 'descuento_de_cheques', 'balance_tree')
        for cuenta_id in cuentas_obj_ids:
            cuenta = cuentas_obj.browse(cr, uid, cuenta_id, context=None)
            cuenta.actsaldo(cr)
        return {
                'name': ('Cuentas'),
                'view_type': 'form',
                'view_mode': 'tree',
                'res_model': 'account.account',
                'view_id': view_id,
                'tag': 'reload',
                'type': 'ir.actions.act_window',
                'context': context,
                }
