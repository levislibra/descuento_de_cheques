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

import openerp.addons.cheques_de_terceros

# Add a new floats fields and date object cheques.de.terceros
class tasas_add_fields(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'

    _columns = {
		'tasa_fija_descuento': fields.float('Tasa Fija'),
        'tasa_mensual_descuento': fields.float('Tasa Mensual'),
        'fecha_acreditacion_descuento': fields.float('Fecha de acreditacion'),
    }

# Add a new floats fields object res.partner
class res_partner_add_fields(osv.Model):
    # This OpenERP object inherits from res.partner
    # to add a new textual field
    _inherit = 'res.partner'
    #'res.partner'

    _columns = {
        'tasa_fija_recomendada' : fields.float('Tasa Fija Recomendada'),
        'tasa_mensual_recomendada' : fields.float('Tasa Mensual Recomendada'),
    }


class descuento_de_cheques(osv.Model):
    _name = 'descuento.de.cheques'
    _description = 'liquidacion de cheques'
    _rec_name = 'id'
    _columns =  {
        'id': fields.integer('Nro liquidacion'),
        'fecha_liquidacion': fields.date('Fecha liquidacion'),
        'active': fields.boolean('Activa', help="Cancelar liquidacion luego de validarla"),
        'cliente_id': fields.many2one('res.partner', 'Cliente'),
        'cheques_ids': fields.one2many('cheques.de.terceros', 'id', 'Cheques', ondelete='cascade'),


        'name': fields.char("Numero del cheque", size=8),
        'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada')], string='Status', readonly=True, track_visibility='onchange'),
    }
    _defaults = {
    	'state': 'cotizacion',
    	'active': True,

    }
    _sql_constraints = [
            ('id_uniq', 'unique (id)', "El Nro de liquidacion ya existe!"),
    ]
