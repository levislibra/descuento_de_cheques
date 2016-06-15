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
        'transferencia_id': fields.many2one('descuento.de.cheques', 'Transferencia id'),
    }

class transferencia(osv.Model):
    _name = 'transferencia'
    _description = 'trensferencias entre cuentas'

    _columns = {
        'fecha': fields.date('Fecha', required=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmada', 'Confirmada'), ('registrado', 'Registrado')], string='Estado', readonly=True),
        'tipo_de_pago': fields.selection([('enviarDinero', 'Enviar dinero'), ('recibirDinero', 'Recibir dinero'), ('transferenciaInterna', 'Transferencia interna')], string='Tipo de pago', required=True),
        'entidad_id': fields.many2one('res.partner', 'Entidad', required=True),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta', required=True),
        'efectivo': fields.boolean('Efectivo'),
        'cuenta_efectivo_id': fields.many2one('account.account', 'Caja'),
        'monto_efectivo': fields.float('Monto efectivo'),
        'cheques': fields.boolean('Cheques'),
        'cuenta_cheques_id': fields.many2one('account.account', 'Cuenta cheques'),
        'cheques_ids': fields.one2many('cheques.de.terceros', 'transferencia_id', 'Cheques'),
        'monto_en_cheques': fields.float('Monto en cheques', readonly=True, compute="_set_monto_cheques"),
        #'metodo_de_pago': fields.selection([('efectivo', 'Efectivo'), ('cheques', 'Cheques')], string='Metodo de pago', required=True),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
        'efectivo': False,
        'Cheques': False,
    }

    @api.depends('cheques_ids')
    def _set_monto_cheques(self):
        _logger.error("_set_monto_cheques")
        self.monto_en_cheques = 0
        for cheque in self.cheques_ids:
            self.monto_en_cheques += cheque.importe
            _logger.error("cheques : %r", cheque.importe)
            _logger.error("Monto : %r", self.monto_en_cheques)

    @api.onchange('entidad_id')
    def _reiniciar_subcuenta_id(self):
        _logger.error("_set_monto_cheques")
        if self.entidad_id:
            self.subcuenta_id = False

    def confirmar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'confirmada'}, context=None)
        return True

    @api.multi
    def registrar(self, cr):
        self.state = 'registrado'

