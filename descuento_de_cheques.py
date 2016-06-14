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


class account_journal(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'account.journal'
    _name = 'account.journal'
    _description = 'opciones extras de cheques para calculo del descuento'

    _columns = {
        'cuenta_cheques_id': fields.many2one('account.account', 'Cuenta de cheques predeterminada'),
        'cuenta_ganancia_id': fields.many2one('account.account', 'Cuenta Ganancia predeterminada'),
        'cuenta_caja_id': fields.many2one('account.account', 'Cuenta caja predeterminada'),
    }



# Add a new floats fields and date object cheques.de.terceros
class cheques_de_terceros(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'cheques.de.terceros'
    _name = 'cheques.de.terceros'
    _description = 'opciones extras de cheques para calculo del descuento'

    _columns = {
        'liquidacion_id': fields.many2one('descuento.de.cheques', 'Liquidacion id'),
		'tasa_fija_descuento': fields.float('% Fija'),#, compute="_calcular_descuento_tasas"
		'monto_fijo_descuento': fields.float(string='Gasto', compute='_calcular_descuento_fijo'),
        'tasa_mensual_descuento': fields.float('% Mensual'),#, compute="_calcular_descuento_tasas"
        'monto_mensual_descuento': fields.float(string='Interes', compute='_calcular_descuento_mensual'),
        'fecha_acreditacion_descuento': fields.date('Acreditacion'),#, compute='_calcular_fecha_acreditacion'
        'monto_neto_descuento': fields.float(string='Neto', compute='_calcular_descuento_neto'),
        'dias_descuento': fields.integer(string='Dias', compute='_calcular_descuento_dias')
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
            ultimos_dias = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            i = 0
            fines_de_mes = []
            while fecha_inicial < fecha_final:
                ano_actual = fecha_inicial.year
                mes_actual = fecha_inicial.month
                dia_actual_fin_de_mes = ultimos_dias[mes_actual-1]
                fecha_fin_de_mes_str = str(ano_actual)+"-"+str(mes_actual)+"-"+str(dia_actual_fin_de_mes)
                fecha_fin_de_mes = datetime.strptime(fecha_fin_de_mes_str, formato_fecha)
                if fecha_fin_de_mes >= fecha_inicial and fecha_fin_de_mes <= fecha_final:
                    _logger.error("FECHA ADD")
                    fines_de_mes.append(fecha_fin_de_mes)

                if mes_actual == 12:
                    mes_proximo = 1
                    ano_proximo = ano_actual + 1
                else:
                    mes_proximo = mes_actual + 1
                    ano_proximo = ano_actual
                dia_proximo = 15
                fecha_inicial_str = str(ano_proximo)+"-"+str(mes_proximo)+"-"+str(dia_proximo)
                fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
                i = i + 1
            _logger.error("RESULTADO: %r", fines_de_mes)


            




            
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
    _description = 'liquidacion de cheques'
    #_inherits = { 'res.partner' : 'subcuenta_ids'}
    _rec_name = 'id'
    _columns =  {
        'id': fields.integer('Nro liquidacion'),
        'fecha_liquidacion': fields.date('Fecha', required=True),
        'active': fields.boolean('Activa'),
        'cliente_id': fields.many2one('res.partner', 'Cliente', required=True),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta', required=True),
        'journal_id': fields.many2one('account.journal', 'Diario', required=True),
        'move_id':fields.many2one('account.move', 'Asiento', readonly=True),
        'invoice_id':fields.many2one('account.invoice', 'Factura', readonly=True),
        'efectivo_al_cliente':fields.float('Efectivo al cliente'),
        'cheques_ids': fields.one2many('cheques.de.terceros', 'liquidacion_id', 'Cheques', ondelete='cascade'),
        'state': fields.selection([('cotizacion', 'Cotizacion'), ('confirmada', 'Confirmada'), ('pagado', 'Pagado'), ('cancelada', 'Cancelada')], string='Status', readonly=True, track_visibility='onchange'),

        'cliente_subcuenta_ids': fields.one2many('subcuenta', 'descuento_id', related='cliente_id.subcuenta_ids', readonly=True, store=False),
        'bruto_liquidacion': fields.float(string='Bruto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_liquidacion': fields.float(string='Gasto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'interes_liquidacion': fields.float(string='Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'gasto_interes_liquidacion': fields.float(string='Gasto + Interes', compute='_calcular_montos_liquidacion', readonly=True, store=True),
        'neto_liquidacion': fields.float(string='Neto', compute='_calcular_montos_liquidacion', readonly=True, store=True),
    }

    @api.one
    @api.constrains('subcuenta_id')
    def _check_description(self):
        _logger.error("##########________ self.subcuenta_id.subcuenta_id.id: %r", self.subcuenta_id.subcuenta_id.name)
        _logger.error("##########________ self.cliente_id.id: %r", self.cliente_id.name)
        if self.subcuenta_id.subcuenta_id.id != self.cliente_id.id:
            raise ValidationError("La subcuenta no pertenece al cliente")

        #if self.subcuenta_id.state != 'activa':
            #raise ValidationError("La subcuenta no esta Activa")

    @api.one
    @api.constrains('fecha_liquidacion', 'subcuenta_id')
    def _check_fecha_liquidacion_subcuenta(self):
        _logger.error("Constrain Fechaaaaaaaaaaaaa")
        _logger.error("apuntes ids: %r", self.subcuenta_id.apuntes_ids)
        if self.subcuenta_id.apuntes_ids:
            last_date_move_line = self.subcuenta_id.apuntes_ids[0].date
            _logger.error("apuntes fecha last: %r", last_date_move_line)
            if self.fecha_liquidacion < last_date_move_line:
                text_error = "La fecha de la liquidacion (" + str(self.fecha_liquidacion) + ") no puede ser menos a la ultima fecha de la subcuenta (" + str(last_date_move_line) +")"
                raise ValidationError(text_error)



    @api.one
    @api.constrains('journal_id')
    def _check_description(self):
        _logger.error("JOURNAL ID: ")
        if self.journal_id.cuenta_cheques_id == False:
            raise ValidationError("En el Diario, la cuenta cheques no esta definida.")
        if self.journal_id.cuenta_ganancia_id == False:
            raise ValidationError("En el Diario, la cuenta ganancia no esta definida.")
        if self.journal_id.cuenta_caja_id == False:
            raise ValidationError("En el Diario, la cuenta caja no esta definida.")


    @api.onchange('cliente_id')
    def _calcular_cliente_subcuenta_id(self):
        _logger.error("########## _subcuenta_id ######################")
        if self.cliente_id:
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

    def confirmar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'confirmada'}, context=None)
        return True

    def editar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'cotizacion'}, context=None)
        return True


    @api.multi
    def pagar(self, cr):
        self.state = 'pagado'
        descuento_name = "Descuento/" + str(self.id)
        name_move_line = "Descuento de "
        for cheque in self.cheques_ids:
            cheque.state = 'en_cartera'
            name_move_line += "cheque " + cheque.banco_id.name + " Nro " + cheque.name + ", "

        company_id = self.env['res.users'].browse(self.env.uid).company_id.id

        
        if self.bruto_liquidacion > 0:
            #list of move line
            line_ids = []
            # create move line
            # Registro el monto total de los cheques en cuenta de activo
            aml = {
                'date': self.fecha_liquidacion,
                'account_id': self.journal_id.cuenta_cheques_id.id,
                'name': descuento_name + ' - Bruto descuento de cheques',
                'partner_id': self.cliente_id.id,
                'debit': self.bruto_liquidacion,
            }
            line_ids.append((0,0,aml))

            # create move line
            # Acredito el monto total de los cheques al cliente
            aml2 = {
                'date': self.fecha_liquidacion,
                'account_id': self.cliente_id.property_account_receivable_id.id,
                'name': descuento_name + ' - Acredito bruto de cheques',
                'partner_id': self.cliente_id.id,
                'credit': self.bruto_liquidacion,
                'subcuenta_id': self.subcuenta_id.id,
            }
            line_ids.append((0,0,aml2))

            if self.interes_liquidacion > 0:
                # create move line
                # Debito el monto de intereses al cliente
                aml3 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.cliente_id.property_account_receivable_id.id,
                    'name': descuento_name + ' - Intereses',
                    'partner_id': self.cliente_id.id,
                    'debit': self.interes_liquidacion,
                    'subcuenta_id': self.subcuenta_id.id,
                }
                line_ids.append((0,0,aml3))
            else:
                #interes = 0
                pass

            if self.gasto_liquidacion > 0:
                # create move line
                # Debito el monto de gastos al cliente
                aml4 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.cliente_id.property_account_receivable_id.id,
                    'name': descuento_name + ' - Impuesto a los debitos y creditos',
                    'partner_id': self.cliente_id.id,
                    'debit': self.gasto_liquidacion,
                    'subcuenta_id': self.subcuenta_id.id,
                }
                line_ids.append((0,0,aml4))
            else:
                #gastos = 0
                pass

            if self.gasto_interes_liquidacion > 0:
                # create move line
                # Acredito el monto total de intereses mas gastos a cuenta ganancias
                aml5 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.journal_id.cuenta_ganancia_id.id,
                    'name': descuento_name + ' - Intereses mas gastos descontados',
                    'partner_id': self.cliente_id.id,
                    'credit': self.gasto_interes_liquidacion,
                }
                line_ids.append((0,0,aml5))
            else:
                #gasto mas interes = 0
                pass

            if self.efectivo_al_cliente > 0:
                # create move line
                # Debito el monto de efectivo entregado al cliente
                aml6 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.cliente_id.property_account_receivable_id.id,
                    'name': descuento_name + ' - Efectivo al cliente',
                    'partner_id': self.cliente_id.id,
                    'debit': self.efectivo_al_cliente,
                    'subcuenta_id': self.subcuenta_id.id,
                }
                line_ids.append((0,0,aml6))

                # create move line
                # Acredito el monto entregado al cliente de la caja saliente
                aml7 = {
                    'date': self.fecha_liquidacion,
                    'account_id': self.journal_id.cuenta_caja_id.id,
                    'name': descuento_name + ' - Efectivo',
                    'partner_id': self.cliente_id.id,
                    'credit': self.efectivo_al_cliente,
                }
                line_ids.append((0,0,aml7))
            else:
                #efectivo al cliente = 0
                pass
            # create move
            move_name = descuento_name
            move = self.env['account.move'].create({
                'name': move_name,
                'date': self.fecha_liquidacion,
                'journal_id': self.journal_id.id,
                'state':'draft',
                'company_id': company_id,
                'partner_id': self.cliente_id.id,
                'line_ids': line_ids,
            })
            move.state = 'posted'
            self.move_id = move.id
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
            'account_id': self.journal_id.cuenta_ganancia_id.id,
            }

            # Create invoice line
            ail2 = {
            'name': "Impuesto a los debitos y creditos bancarios por cuenta del cliente.",
            'quantity':1,
            'price_unit': self.gasto_liquidacion,
            'account_id': self.journal_id.cuenta_ganancia_id.id,
            }

            account_invoice_customer0 = account_invoice_obj.sudo(self.env.uid).create(dict(
                name=move_name,
                date=self.fecha_liquidacion,
                reference_type="none",
                type="out_invoice",
                reference=False,
                #payment_term_id=self.payment_term.id,
                journal_id=self.journal_id.id,
                partner_id=self.cliente_id.id,
                move_id=move.id,
                #residual=self.gasto_interes_liquidacion,
                #residual_company_signed=self.gasto_interes_liquidacion,
                #residual_signed=self.gasto_interes_liquidacion,
                account_id=self.cliente_id.property_account_receivable_id.id,
                invoice_line_ids=[(0, 0, ail), (0, 0, ail2)]
            ))
            account_invoice_customer0.signal_workflow('invoice_open')
            #account_invoice_customer0.reconciled = True
            account_invoice_customer0.state = 'paid'
            self.invoice_id = account_invoice_customer0.id

        return True

    def cancelar(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state':'cancelada'}, context=None)
        return True
    

    _defaults = {
		'fecha_liquidacion': lambda *a: time.strftime('%Y-%m-%d'),
    	'state': 'cotizacion',
    	'active': True,
    }
    _sql_constraints = [
            ('id_uniq', 'unique (id)', "El Nro de liquidacion ya existe!"),
    ]
