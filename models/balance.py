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
        #faltan campos derivados
        #saldo
        'saldo' : fields.float('Saldo', readonly=True),
        'move_line_ids': fields.one2many('account.move.line', 'account_id', 'Apuntes'),
    }

    _defaults = {
        'saldo': 0,
    }

    @api.multi
    def hola(self, cr):
        _logger.error("HOLAAAAAAAAAA!!! : %r", self)
        apunte_previo = None
        apuntes_ids = self.move_line_ids
        count = len(apuntes_ids)
        self.saldo = 0
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            self.saldo += apunte.debit - apunte.credit
            if apunte_previo != None:
                apunte.sub_saldo = apunte.debit - apunte.credit + apunte_previo.sub_saldo

                apunte.saldo = apunte.debit - apunte.credit + apunte_previo.saldo
            else:
                apunte.sub_saldo = apunte.debit - apunte.credit
                apunte.saldo = apunte.debit - apunte.credit
            apunte_previo = apunte
            i = i + 1
