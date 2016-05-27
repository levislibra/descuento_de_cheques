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
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta'),
    }

#Add a new floats fields object res.partner
class res_partner(osv.Model):
    # This OpenERP object inherits from res.partner
    # to add a subcuenta fields
    _inherit = 'res.partner'

    _columns = {
        'subcuenta_ids' : fields.one2many('subcuenta', 'subcuenta_id', 'Subcuentas'),
    }

class subcuenta(osv.Model):
    _name = 'subcuenta'
    _description = 'subcuenta'
    _columns =  {
        'name': fields.char('Subcuenta', required=True),
        'subcuenta_id': fields.many2one('res.partner', 'Cliente'),
        'active': fields.boolean('Activa'),
        'cuenta_corriente': fields.boolean('Cuenta Corriente'),
        'apunte_ids': fields.one2many('account.move.line', 'subcuenta_id', 'Apuntes'),
        #faltan campos derivados
        #saldo
    }

    _defaults = {
    	'active': True,
        'cuenta_corriente': False,
    }
