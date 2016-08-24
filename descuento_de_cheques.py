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
import models.subcuenta
_logger = logging.getLogger(__name__)
#       _logger.error("date now : %r", date_now)


# Add a new floats fields and date object cheques.de.terceros
class cheques_de_terceros(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'
    _name = 'cheques.de.terceros'
    _description = 'opciones extras de cheques para calculo del descuento'
    _order = "fecha_vencimiento, id"
    _columns = {
        'liquidacion_id': fields.many2one('descuento.de.cheques', 'Liquidacion id'),
		'tasa_fija_descuento': fields.float('% Fija'),
		'monto_fijo_descuento': fields.float(string='Gasto', compute='_calcular_descuento_fijo'),
        'tasa_mensual_descuento': fields.float('% Mensual'),
        'monto_mensual_descuento': fields.float(string='Interes', compute='_calcular_descuento_mensual'),
        'fecha_acreditacion_descuento': fields.date('Acreditacion'),
        'monto_neto_descuento': fields.float(string='Neto', compute='_calcular_descuento_neto'),
        'dias_descuento': fields.integer(string='Dias', compute='_calcular_descuento_dias'),
        'journal_id': fields.many2one('account.journal', 'Diario'),
        #Origen
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', string='Cuenta'),
        'subcuenta_id': fields.many2one('subcuenta', string='Subcuenta'),
        'entidad_id': fields.many2one('res.partner', related='cuenta_entidad_id.entidad_id', string='Entidad'),
        #Destino
        'cuenta_entidad_destino_id': fields.many2one('cuenta.entidad', string='Cuenta destino'),
        'subcuenta_destino_id': fields.many2one('subcuenta', string='Subcuenta destino'),
        'entidad_destino_id': fields.many2one('res.partner', related='cuenta_entidad_destino_id.entidad_id', string='Entidad destino'),
        'form_rechazo_cheque_id': fields.many2one('form.rechazo.cheque', string='Formulario de rechazo'),
    }

    @api.one
    @api.depends('importe', 'tasa_fija_descuento')
    def _calcular_descuento_fijo(self):
        _logger.error("_calcular_descuento_fijo")
    	self.monto_fijo_descuento = self.importe * (self.tasa_fija_descuento / 100)

    @api.one
    @api.depends('importe', 'tasa_mensual_descuento', 'dias_descuento')
    def _calcular_descuento_mensual(self):
        _logger.error("_calcular_descuento_mensual")
    	self.monto_mensual_descuento = self.dias_descuento * ((self.tasa_mensual_descuento / 30) / 100) * self.importe


    @api.one
    @api.depends('liquidacion_id.fecha_liquidacion', 'fecha_acreditacion_descuento')
    def _calcular_descuento_dias(self):
        fecha_inicial_str = False
        fecha_final_str = False
        _logger.error("_calcular_descuento_dias")
        _logger.error("Fecha_inicial antes: %r",fecha_inicial_str)
        if self.liquidacion_id.fecha_liquidacion != False:
    	   fecha_inicial_str = str(self.liquidacion_id.fecha_liquidacion)
        if self.fecha_acreditacion_descuento != False:
    	   fecha_final_str = str(self.fecha_acreditacion_descuento)
        _logger.error("fecha_inicial: %r",fecha_inicial_str)
        _logger.error("fecha_final: %r",fecha_final_str)

    	if fecha_inicial_str != False and fecha_final_str != False:
            formato_fecha = "%Y-%m-%d"
            fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
            fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
            diferencia = fecha_final - fecha_inicial
            
            if diferencia.days > 0:
                self.dias_descuento = diferencia.days
            else:
                self.dias_descuento = 0


    #Ojo -- actualizar bien esta funcion.
    @api.onchange('name')
    def _calcular_descuento_tasas(self):
        _logger.error("_calcular_descuento_tasas")
        if self.liquidacion_id is not None and self.liquidacion_id.subcuenta_id is not None:
            self.tasa_fija_descuento = self.liquidacion_id.subcuenta_id.tasa_fija_descuento
            self.tasa_mensual_descuento = self.liquidacion_id.subcuenta_id.tasa_mensual_descuento

    @api.onchange('fecha_vencimiento')
    def _calcular_fecha_acreditacion(self):
        _logger.error("_calcular_descuento_fecha_acreditacion")
        self.fecha_acreditacion_descuento = self.fecha_vencimiento


    @api.one
    @api.depends('monto_fijo_descuento', 'monto_mensual_descuento')
    def _calcular_descuento_neto(self):
        _logger.error("_calcular_descuento_neto")
    	self.monto_neto_descuento = self.importe - self.monto_fijo_descuento - self.monto_mensual_descuento


class descuento_de_cheques(osv.Model):
    _name = 'descuento.de.cheques'
    _description = 'Liquidacion de cheques'

    _rec_name = 'id'
    _columns =  {
        'id': fields.integer('Nro liquidacion'),
        'fecha_liquidacion': fields.date('Fecha', required=True),
        'active': fields.boolean('Activa'),
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta', required=True),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta', domain="[('cuenta_entidad_id.id', '=', cuenta_entidad_id), ('descuento_de_cheques','=', True)]", required=True),

        'journal_id': fields.many2one('account.journal', 'Diario', required=True),
        'move_confirmacion_id':fields.many2one('account.move', 'Asiento confirmacion', readonly=True),
        'move_pago_id':fields.many2one('account.move', 'Asiento pago', readonly=True),
        'invoice':fields.boolean('Emitir factura'),
        'invoice_id':fields.many2one('account.invoice', 'Factura', readonly=True),
        'form_confirmar_descuento_id': fields.many2one("form.confirmar.descuento", "Registro de confirmacion", readonly=True),
        'descuento_pago_id': fields.many2one("descuento.pago", "Comprobante de pago", readonly=True),
        'cheques_ids': fields.one2many('cheques.de.terceros', 'liquidacion_id', 'Cheques', ondelete='cascade'),
        'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada'), ('pagado', 'Pagado'), ('cancelada', 'Cancelada')], string='Status', readonly=True, track_visibility='onchange'),

        'cuenta_subcuentas_ids': fields.one2many('subcuenta', 'descuento_id', related='cuenta_entidad_id.subcuentas_ids', readonly=True, store=False),
        'bruto_liquidacion': fields.float(string='Bruto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_liquidacion': fields.float(string='Gasto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'interes_liquidacion': fields.float(string='Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_interes_liquidacion': fields.float(string='Gasto + Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'neto_liquidacion': fields.float(string='Neto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
    }

    @api.one
    @api.constrains('subcuenta_id')
    def _check_description(self):
        if self.subcuenta_id.cuenta_entidad_id.id != self.cuenta_entidad_id.entidad_id.id:
            raise ValidationError("La subcuenta no pertenece al cliente")

        #if self.subcuenta_id.state != 'activa':
            #raise ValidationError("La subcuenta no esta Activa")

#    @api.one
#    @api.constrains('fecha_liquidacion', 'subcuenta_id')
#    def _check_fecha_liquidacion_subcuenta(self):
#        if self.subcuenta_id.apuntes_ids:
#            last_date_move_line = self.subcuenta_id.apuntes_ids[0].date
#            _logger.error("apuntes fecha last: %r", last_date_move_line)
#            if self.fecha_liquidacion < last_date_move_line:
#                text_error = "La fecha de la liquidacion (" + str(self.fecha_liquidacion) + ") no puede ser menos a la ultima fecha de la subcuenta (" + str(last_date_move_line) +")"
#                raise ValidationError(text_error)



    @api.one
    @api.constrains('journal_id')
    def _check_description(self):
        _logger.error("JOURNAL ID: ")
        if self.journal_id.default_debit_account_id == False:
            raise ValidationError("En el Diario, la cuenta no esta definida.")

    @api.onchange('cuenta_entidad_id')
    def _calcular_cliente_subcuenta_id(self):
        if self.cuenta_entidad_id.entidad_id:
            self.subcuenta_id = False

    @api.one
    @api.depends('cheques_ids')
    def _calcular_montos_liquidacion(self):
        self.bruto_liquidacion = 0
        self.gasto_liquidacion = 0
        self.interes_liquidacion = 0
        self.gasto_interes_liquidacion = 0
        self.neto_liquidacion = 0
        for cheque in self.cheques_ids:
            self.bruto_liquidacion += cheque.importe
            self.gasto_liquidacion += cheque.monto_fijo_descuento
            self.interes_liquidacion += cheque.monto_mensual_descuento
            self.gasto_interes_liquidacion += cheque.monto_fijo_descuento + cheque.monto_mensual_descuento
            self.neto_liquidacion += cheque.monto_neto_descuento


    @api.multi
    def confirmar(self):
        self.state = 'confirmada'

        cuenta_cheques_id = None
        if self.form_confirmar_descuento_id.journal_id.default_debit_account_id == False:
            raise ValidationError("En el Diario, la cuenta cheques no esta definida.")
        else:
            cuenta_cheques_id = self.form_confirmar_descuento_id.journal_id.default_debit_account_id.id

        descuento_name = "Descuento/" + str(self.id)
        name_move_line = "Descuento de "
        for cheque in self.cheques_ids:
            cheque.state = 'en_cartera'
            name_move_line += "cheque " + cheque.banco_id.name + " Nro " + cheque.name + ", "
            cheque.journal_id = self.form_confirmar_descuento_id.journal_id.id
            cheque.cuenta_entidad_id = self.cuenta_entidad_id.id
            cheque.subcuenta_id = self.subcuenta_id.id

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id

        if self.bruto_liquidacion > 0:
            #list of move line
            line_ids = []
            # create move line
            # Registro el monto total de los cheques en cuenta de activo
            aml = {
                'date': self.fecha_liquidacion,
                'account_id': cuenta_cheques_id,
                'name': descuento_name + ' - Bruto descuento de cheques',
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'debit': self.bruto_liquidacion,
            }
            line_ids.append((0,0,aml))

            # create move line
            # Acredito el neto al cliente
            aml2 = {
                'date': self.fecha_liquidacion,
                'account_id': self.cuenta_entidad_id.entidad_id.property_account_receivable_id.id,
                'name': descuento_name + ' - Acredito neto del descuento',
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'credit': self.neto_liquidacion,
                'subcuenta_id': self.subcuenta_id.id,
            }
            line_ids.append((0,0,aml2))

            if self.gasto_interes_liquidacion > 0:
                # create move line
                # Acredito el monto total de intereses mas gastos a cuenta ganancias
                aml3 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.journal_id.default_debit_account_id.id,
                    'name': descuento_name + ' - Intereses mas gastos descontados',
                    'partner_id': self.cuenta_entidad_id.entidad_id.id,
                    'credit': self.gasto_interes_liquidacion,
                }
                line_ids.append((0,0,aml3))

            if self.invoice and False:
                # create move line
                # Acredito el monto de IVA a la cuenta respectiva (GASTOS)
                monto_iva = self.interes_liquidacion * 0.21
                aml4 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.subcuenta_id.account_id.id,
                    'name': descuento_name + ' - IVA',
                    'partner_id': self.cuenta_entidad_id.entidad_id.id,
                    'credit': monto_iva,
                    'subcuenta_id': self.subcuenta_id.id,
                }
                line_ids.append((0,0,aml4))

            # create move
            move_name = descuento_name
            move = self.env['account.move'].create({
                'name': move_name,
                'date': self.fecha_liquidacion,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'line_ids': line_ids,
            })
            move.state = 'posted'
            self.move_confirmacion_id = move.id
            #self.subcuenta_id._actualizar_previos()
            self.subcuenta_id._actualizar_saldo_acumulado()
        else:
            #bruto = 0
            pass

        if self.gasto_interes_liquidacion > 0:
            account_invoice_obj = self.env['account.invoice']
            # Create invoice line
            ail = {
                'name': name_move_line,
                'quantity':1,
                'price_unit': self.interes_liquidacion,
                'account_id': self.journal_id.default_debit_account_id.id,
            }

            # Create invoice line
            ail2 = {
                'name': "Impuesto a los debitos y creditos bancarios por cuenta del cliente.",
                'quantity':1,
                'price_unit': self.gasto_liquidacion,
                'account_id': self.journal_id.default_debit_account_id.id,
            }

            if self.invoice:

                account_invoice_customer0 = account_invoice_obj.sudo(self.env.uid).create(dict(
                    name=move_name,
                    date=self.fecha_liquidacion,
                    reference_type="none",
                    type="out_invoice",
                    reference=False,
                    #payment_term_id=self.payment_term.id,
                    journal_id=self.journal_id.id,
                    partner_id=self.cuenta_entidad_id.entidad_id.id,
                    move_id=move.id,
                    #residual=self.gasto_interes_liquidacion,
                    #residual_company_signed=self.gasto_interes_liquidacion,
                    #residual_signed=self.gasto_interes_liquidacion,
                    account_id=self.subcuenta_id.account_id.id,
                    invoice_line_ids=[(0, 0, ail), (0, 0, ail2)]
                ))
                account_invoice_customer0.signal_workflow('invoice_open')
                #account_invoice_customer0.reconciled = True
                account_invoice_customer0.state = 'paid'
                self.invoice_id = account_invoice_customer0.id
   
        return True

    def editar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'cotizacion'}, context=None)
        return True


    @api.multi
    def pagar(self):
        self.state = 'pagado'
        descuento_name = "Pago/Descuento/" + str(self.id)
        company_id = self.env['res.users'].browse(self.env.uid).company_id.id

        monto = self.descuento_pago_id.monto
        if self.subcuenta_id.tipo == 'activo':
            account_id = self.cuenta_entidad_id.account_cobrar_id.id
        else:
            account_id = self.cuenta_entidad_id.account_pagar_id.id
        
        #Metodo de pago
        journal_id = self.descuento_pago_id.journal_id

        line_ids = []
        if monto > 0:
            # create move line
            # Debito el monto de efectivo entregado al cliente
            aml6 = {
                'date': self.fecha_liquidacion,
                'account_id': account_id,
                'name': descuento_name + ' - Neto al cliente',
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'debit': monto,
                'subcuenta_id': self.subcuenta_id.id,
            }
            line_ids.append((0,0,aml6))

            # create move line
            # Acredito el monto entregado al cliente de la cuenta saliente
            aml7 = {
                'date': self.fecha_liquidacion,
                'account_id': journal_id.default_debit_account_id.id,
                'name': descuento_name + ' - Pago',
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'credit': monto,
            }
            line_ids.append((0,0,aml7))
        
            # create move
            move_name = descuento_name
            move = self.env['account.move'].create({
                'name': move_name,
                'date': self.fecha_liquidacion,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'line_ids': line_ids,
            })
            move.state = 'posted'
            self.move_pago_id = move.id
            #self.subcuenta_id._actualizar_previos()
            self.subcuenta_id._actualizar_saldo_acumulado()

        else:
            #efectivo al cliente = 0
            pass

        return True

    def cancelar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'cancelada'}, context=None)
        return True
    

    _defaults = {
		'fecha_liquidacion': lambda *a: time.strftime('%Y-%m-%d'),
    	'state': 'cotizacion',
    	'active': True,
        'invoice': False,
    }
    _sql_constraints = [
            ('id_uniq', 'unique (id)', "El Nro de liquidacion ya existe!"),
    ]

class form_confirmar_descuento(osv.Model):
    _name = 'form.confirmar.descuento'
    _description = 'Informacion para la confirmacion del descuento'
    _rec_name= "name"
    _order = "id desc"
    _columns = {
        'id': fields.integer("ID", readonly=True),
        'name': fields.char("ID", readonly=True, compute="compute_name"),
        'fecha': fields.date("Fecha", required=True),
        'monto': fields.float("Bruto Cheques", readonly=True),
        'journal_id': fields.many2one('account.journal', string="Cartera de cheques", required=True, domain="[('type', 'in', ('bank', 'cash'))]"),
        'descuento_id': fields.many2one("descuento.de.cheques", "Descuento", readonly=True),
        'move_id': fields.many2one("account.move", "Asiento", readonly=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmado', 'Confirmado')], string='Estado', readonly=True),
    }

    @api.one
    @api.depends('journal_id')
    def compute_name(self):
        self.name = "Confirmacion/" + self.journal_id.name + "/" + str(self.id)

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
    }

    @api.model
    def default_get(self, fields):
        rec = super(form_confirmar_descuento, self).default_get(fields)
        context = dict(self._context or {})
        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        # Checks on context parameters
        if not active_model or not active_ids:
            raise UserError(_("Programmation error: wizard action executed without active_model or active_ids in context."))
        if active_model != 'descuento.de.cheques':
            raise UserError(_("Programmation error: the expected model for this action is 'descuento.de.cheques'. The provided one is '%d'.") % active_model)

        # Checks on received cuotas records
        descuento = self.env[active_model].browse(active_id)
        total_amount = descuento[0].bruto_liquidacion
        rec.update({
            'monto': abs(total_amount),
            'descuento_id': active_id,
            'fecha': descuento[0].fecha_liquidacion,
        })
        return rec

    def _get_descuento(self):
        return self.env['descuento.de.cheques'].browse(self._context.get('active_id'))[0]

    def asingnar_move(self, move):
        self.move_id = move.id
        return True

    @api.one
    def validar_confirmacion(self):
        descuento = self._get_descuento()
        descuento.form_confirmar_descuento_id = self.id
        descuento.confirmar()
        self.state = 'confirmado'
        return {'type': 'ir.actions.act_window_close'}

class descuento_pago(osv.Model):
    _name = 'descuento.pago'
    _description = 'Informacion del pago del descuento'
    _rec_name= "name"
    _order = "id desc"
    _columns = {
        'id': fields.integer("ID", readonly=True),
        'name': fields.char("ID", readonly=True, compute="compute_name"),
        'fecha': fields.date("Fecha", required=True),
        'monto': fields.float("Monto a entregar"),
        'journal_id': fields.many2one('account.journal', string="Metodo de Pago", required=True, domain="[('type', 'in', ('bank', 'cash'))]"),
        'descuento_id': fields.many2one("descuento.de.cheques", "Descuento", readonly=True),
        'move_id': fields.many2one("account.move", "Asiento", readonly=True),
        'state': fields.selection([('borrador', 'Borrador'), ('confirmado', 'Confirmado')], string='Estado', readonly=True),
    }

    @api.one
    @api.depends('journal_id')
    def compute_name(self):
        self.name = "Comprobante/" + self.journal_id.name + "/" + str(self.id)

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
    }

    @api.model
    def default_get(self, fields):
        rec = super(descuento_pago, self).default_get(fields)
        context = dict(self._context or {})
        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        # Checks on context parameters
        if not active_model or not active_ids:
            raise UserError(_("Programmation error: wizard action executed without active_model or active_ids in context."))
        if active_model != 'descuento.de.cheques':
            raise UserError(_("Programmation error: the expected model for this action is 'descuento.de.cheques'. The provided one is '%d'.") % active_model)

        # Checks on received cuotas records
        descuento = self.env[active_model].browse(active_id)
        total_amount = descuento[0].neto_liquidacion
        rec.update({
            'monto': abs(total_amount),
            'descuento_id': active_id,
            'fecha': descuento[0].fecha_liquidacion,
        })
        return rec

    def _get_descuento(self):
        return self.env['descuento.de.cheques'].browse(self._context.get('active_id'))[0]

    def asingnar_move(self, move):
        self.move_id = move.id
        return True

    @api.one
    def validar_pago(self):
        monto = self.monto
        descuento = self._get_descuento()
        descuento.descuento_pago_id = self.id
        descuento.pagar()
        #self.crear_move_pago()
        self.state = 'confirmado'
#        else:
#            raise ValidationError("El monto no coincide con el prestamo")
        return {'type': 'ir.actions.act_window_close'}


class form_rechazo_cheque(osv.Model):
    _name = 'form.rechazo.cheque'
    _description = 'Opciones con cheques'
    _rec_name= "id"
    _order = "id desc"
    _columns = {
        'id': fields.integer("ID", readonly=True),
        'fecha': fields.date("Fecha", required=True),
        'monto': fields.float("Monto", readonly=True),
        'detalle': fields.text("Detalle"),
        
        'cuenta_entidad_id': fields.many2one('cuenta.entidad', 'Cuenta origen', required=True),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta origen', domain="[('cuenta_entidad_id.id', '=', cuenta_entidad_id), ('descuento_de_cheques','=', True)]", required=True),
        'aplicar_gasto': fields.boolean("Aplicar gastos"),
        'journal_id': fields.many2one('account.journal', string="Diario Cheques Rechazados", required=True),
        'monto_gasto_pagar': fields.float("Monto a pagar a la cuenta Destino"),
        'monto_gasto_cobrar': fields.float("Monto a cobrar a la cuenta Origen"),
        'diferencia': fields.float("Diferencia", readonly=True),
        'journal_ganancia_id': fields.many2one('account.journal', string="Diario ganancia"),

        'cuenta_entidad_destino_id': fields.many2one('cuenta.entidad', 'Cuenta destino'),
        'subcuenta_destino_id': fields.many2one('subcuenta', 'Subcuenta destino', domain="[('cuenta_entidad_id.id', '=', cuenta_entidad_destino_id), ('descuento_de_cheques','=', True)]"),
        'account_destino_id': fields.many2one('account.account', 'Cuenta contable destino', required=True),
    }

    _defaults = {
        'fecha': lambda *a: time.strftime('%Y-%m-%d'),
        'state': 'borrador',
    }

    @api.onchange('monto_gasto_pagar')
    def _compute_monto_gasto_cobrar(self):
        self.monto_gasto_cobrar = self.monto_gasto_pagar

    @api.onchange('monto_gasto_pagar', 'monto_gasto_cobrar')
    def _compute_diferencia(self):
        self.diferencia = self.monto_gasto_cobrar - self.monto_gasto_pagar

    @api.model
    def default_get(self, fields):
        rec = super(form_rechazo_cheque, self).default_get(fields)
        context = dict(self._context or {})
        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        # Checks on context parameters
        if not active_model or not active_ids:
            raise UserError(_("Programmation error: wizard action executed without active_model or active_ids in context."))
        if active_model != 'cheques.de.terceros':
            raise UserError(_("Programmation error: the expected model for this action is 'descuento.de.cheques'. The provided one is '%d'.") % active_model)
        if len(active_ids) > 1:
            raise UserError(_("Cuidado, solo puede cargar de a uno los cheques."))

        cheque = self.env[active_model].browse(active_id)[0]
        #if cheque.state != 'depositado' and cheque.state != 'enpago':
        #    raise UserError(_("No puedes procesar un rechazo si no fue 'Depositado' o dado 'En Pago' previamente."))

        name = 'Cheque rechazado / Banco ' + cheque.banco_id.name + ' / ' + cheque.name
        rec.update({
            'monto': cheque.importe,
            'cuenta_entidad_id': cheque.cuenta_entidad_id.id,
            'subcuenta_id': cheque.subcuenta_id.id,
            'detalle': name,
            'cuenta_entidad_destino_id': cheque.cuenta_entidad_destino_id.id,
            'subcuenta_destino_id': cheque.subcuenta_destino_id.id,
            'account_destino_id': cheque.account_destino_id.id,
        })
        return rec

    def _get_cheque(self):
        return self.env['cheques.de.terceros'].browse(self._context.get('active_id'))[0]

    def _crear_asiento(self):
        cheque = self._get_cheque()
        line_cheque_rechazado_ids = []
        #line_gastos_cheque_ids = []

        account_id = None
        if self.subcuenta_id.tipo == 'activo':
            account_id = self.cuenta_entidad_id.account_cobrar_id.id
        else:
            account_id = self.cuenta_entidad_id.account_pagar_id.id
        
        # create move line
        # Debito el cheque rechazado al cliente seleccionado/origen del cheque
        
        aml = {
            'date': self.fecha,
            'account_id': account_id,
            'name': self.detalle,
            'partner_id': self.cuenta_entidad_id.entidad_id.id,
            'debit': self.monto,
            'subcuenta_id': self.subcuenta_id.id,
        }
        line_cheque_rechazado_ids.append((0,0,aml))

        if self.aplicar_gasto and self.monto_gasto_cobrar > 0:
            # create move line
            # Debito el el gasto del cheque rechazado al cliente seleccionado/origen del cheque
            
            aml2 = {
                'date': self.fecha,
                'account_id': account_id,
                'name': "Gasto " + self.detalle,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'debit': self.monto_gasto_cobrar,
                'subcuenta_id': self.subcuenta_id.id,
            }
            line_cheque_rechazado_ids.append((0,0,aml2))

            aml3 = {
                'date': self.fecha,
                'account_id': self.journal_id.default_debit_account_id.id,
                'name': "Gasto " + self.detalle,
                'partner_id': self.cuenta_entidad_id.entidad_id.id,
                'credit': self.monto_gasto_cobrar,
            }
            line_cheque_rechazado_ids.append((0,0,aml3))

        account_destino_id = None
        if cheque.subcuenta_destino_id != False and cheque.subcuenta_destino_id.tipo == 'activo':
            account_destino_id = cheque.cuenta_entidad_destino_id.account_cobrar_id.id
        elif cheque.subcuenta_destino_id != False and cheque.subcuenta_destino_id.tipo == 'pasivo':
            account_destino_id = cheque.cuenta_entidad_destino_id.account_pagar_id.id
        elif cheque.subcuenta_destino_id == False and cheque.account_destino_id != False:
            account_destino_id = cheque.account_destino_id.id
        else:
            raise UserError(_("El cheque no tiene definido correctamente la cuenta destino."))

        # create move line
        # Acredito el cheque rechazado a la cuenta destino
        aml4 = {
            'date': self.fecha,
            'account_id': account_destino_id,
            'name': self.detalle,
            'partner_id': cheque.cuenta_entidad_destino_id.entidad_id.id,
            'credit': self.monto,
            'subcuenta_id': cheque.subcuenta_destino_id.id,
        }
        line_cheque_rechazado_ids.append((0,0,aml4))

        if self.aplicar_gasto and self.monto_gasto_pagar > 0:
            # create move line
            # Acredito el gasto del cheque rechazado a la cuenta destino
            aml5 = {
                'date': self.fecha,
                'account_id': account_destino_id,
                'name': "Gasto " + self.detalle,
                'partner_id': cheque.cuenta_entidad_destino_id.entidad_id.id,
                'credit': self.monto_gasto_pagar,
                'subcuenta_id': cheque.subcuenta_destino_id.id,
            }
            line_cheque_rechazado_ids.append((0,0,aml5))

            # create move line
            # Debito a la cuenta de cheques rechazados el monto
            aml6 = {
                'date': self.fecha,
                'account_id': self.journal_id.default_debit_account_id.id,
                'name': "Gasto " + self.detalle,
                'partner_id': cheque.cuenta_entidad_destino_id.entidad_id.id,
                'debit': self.monto_gasto_pagar,
            }
            line_cheque_rechazado_ids.append((0,0,aml6))

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        # create move
        move_name = "Cheque Rechazado/" + str(self.id)
        move = self.env['account.move'].create({
            'name': move_name,
            'date': self.fecha,
            'journal_id': self.journal_id.id,
            'state':'draft',
            'company_id': company_id,
            'partner_id': self.cuenta_entidad_id.entidad_id.id,
            'line_ids': line_cheque_rechazado_ids,
        })
        move.state = 'posted'
        self.subcuenta_id._actualizar_saldo_acumulado()
        if cheque.subcuenta_destino_id != False:
            cheque.subcuenta_destino_id._actualizar_saldo_acumulado()

        return True

    @api.one
    def validar_pago(self):
        self._crear_asiento()
        cheque = self._get_cheque()
        cheque.state = 'rechazado'
        cheque.form_rechazo_cheque_id = self.id
        #self.state = 'confirmado'
        return {'type': 'ir.actions.act_window_close'}
