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
        'interes_generado': fields.boolean('Interes Generado'),
        'saldo_acumulado': fields.float('Saldo Acumulado'),
        'formulario_interes_id': fields.many2one('formulario.interes', 'Formulario Interes'),
    }

    _defaults = {
    	'interes_generado': False,
    }
# Add a new floats fields and date object account_move
class account_move(osv.Model):
    # This OpenERP object inherits from cheques.de.terceros
    # to add a new float field
    _inherit = 'account.move'
    _name = 'account.move'
    _description = 'account.move'

    _columns = {
        'formulario_interes_id': fields.many2one('formulario.interes', 'Formulario Interes'),
    }

#Add a new floats fields object res.partner
class res_partner(osv.Model):
    # This OpenERP object inherits from res.partner
    # toz add a subcuenta fields
    _inherit = 'res.partner'

    _columns = {
        'subcuenta_ids' : fields.one2many('subcuenta', 'subcuenta_id', 'Subcuentas'),
    }

#Add a new object, contains the move.line auto generate
class formularioInteres(osv.Model):
    _name = 'formulario.interes'
    _description = 'Formulario para el calculo de intereses'
    _rec_name = 'id'
    _order = 'id desc'
    _columns = {
        'id': fields.integer('Nro'),
        'fecha_hasta' : fields.date('Fecha hasta', required=True),
        'tipo': fields.selection([('directaMensual', 'Directa Mensual'), ('equivalenteAnual', 'Equivalente anual')], string='Tipo', required=True),
        'state': fields.selection([('pendiente', 'Pendiente'), ('borrador', 'Borrador'), ('confirmado', 'Confirmado'), ('cancelado', 'Cancelado')], string='Estado', readonly=True),
        'tasa_interes' : fields.float('Tasa de interes', required=True),
        'subcuenta_id': fields.many2one('subcuenta', 'Subcuenta'),
        'asientos_ids': fields.one2many('account.move', 'formulario_interes_id', 'Formulario Interes', ondelete='cascade', readonly=True),
        'apuntes_calculados_ids': fields.one2many('account.move.line', 'formulario_interes_id','Apuntes calculados'),
    }

    _defaults = {
        'fecha_hasta': lambda *a: time.strftime('%Y-%m-%d'),
        'tipo': 'directaMensual',
        'state': 'pendiente',
    }

    @api.onchange('tipo')
    def setear_tasa_por_defecto(self):
        _logger.error("onchange tipo")
        if self.subcuenta_id is not None:
            self.tasa_interes = self.subcuenta_id.tasa_descubierto


    @api.one
    @api.constrains('tasa_interes')
    def _check_tasa_interes(self):
        if self.tasa_interes <= 0:
            raise ValidationError("La tasa de interes no puede ser igual o menor que cero.")


    @api.one
    @api.constrains('state')
    def _check_crear_nuevo_formulario(self):
        formulario_interes_ids = self.subcuenta_id.formulario_interes_ids
        formulario_pendiente = False
        if formulario_interes_ids != False:
            for formulario in formulario_interes_ids:
                if formulario.id != self.id and (formulario.state == 'pendiente' or formulario.state == 'borrador'):
                    formulario_pendiente = True
                    break

        if formulario_pendiente:
            raise ValidationError("Existen formulario/s pendientes o en borrador")


    @api.multi
    def generar_intereses(self, cr):
        self.state = 'borrador'
        apunte_previo = None
        move_ids = []
        apuntes_calculados_ids = []
        apuntes_ids = self.subcuenta_id.apuntes_ids
        company_id = self.env['res.users'].browse(self.env.uid).company_id.id
        count = len(apuntes_ids)
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            if apunte_previo is not None:
                if apunte_previo.date <= self.fecha_hasta:
                    apunte.saldo_acumulado = apunte.debit - apunte.credit + apunte_previo.saldo_acumulado
                    if apunte_previo.interes_generado == False:
                        apuntes_calculados_ids.append(apunte_previo.id)
                        apunte_previo.interes_generado = True
                        fechas_bool = apunte_previo.date != apunte.date
                        if fechas_bool:
                            #Cambio de fecha, posible generacion de asiento contable
                            if apunte_previo.saldo_acumulado > 0:
                                fecha_inicial_str = False
                                fecha_final_str = False
                                if apunte_previo.date != False:
                                    fecha_inicial_str = str(apunte_previo.date)
                                if apunte.date != False:
                                    fecha_final_str = str(apunte.date)
                                if fecha_inicial_str != False:
                                    if fecha_final_str != False:
                                        formato_fecha = "%Y-%m-%d"
                                        fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
                                        fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
                                        diferencia = fecha_final - fecha_inicial
                                        
                                        interes = apunte_previo.saldo_acumulado * diferencia.days * self.tasa_interes / 30 / 100
                                        _logger.error("interes: %r", interes)
                                        
                                        # create move line
                                        # Registro el monto de interes en la cuenta de ingreso
                                        detalle = 'Intereses generados - '+ "${0:.2f}".format(apunte_previo.saldo_acumulado)
                                        detalle = detalle + ' x '+ str(diferencia.days) + ' x ('+str(self.tasa_interes)+'% mensual)'
                                        aml = {
                                            'date': apunte.date,
                                            'account_id': self.subcuenta_id.journal_id.cuenta_ganancia_id.id,
                                            'name':  detalle,
                                            'partner_id': apunte.partner_id.id,
                                            'credit': interes,
                                        }

                                        # create move line
                                        # Acredito el monto de intereses a la cuenta del cliente
                                        aml2 = {
                                            'date': apunte.date,
                                            'account_id': apunte.account_id.id,
                                            'name': detalle,
                                            'partner_id': apunte.partner_id.id,
                                            'debit': interes,
                                            'subcuenta_id': apunte.subcuenta_id.id,
                                        }

                                        line_ids = [(0, 0, aml), (0,0, aml2)]

                                        # create move
                                        move_name = "Intereses Generados/"
                                        move = self.env['account.move'].create({
                                            'name': move_name,
                                            'date': apunte.date,
                                            'journal_id': self.subcuenta_id.journal_id.id,
                                            'state':'draft',
                                            'company_id': company_id,
                                            'partner_id': apunte.partner_id.id,
                                            'line_ids': line_ids,
                                        })
                                        #move.state = 'posted'
                                        move_ids.append(move.id)
                                        #Actualizamos la lista!!!!
                                        apuntes_ids = self.subcuenta_id.apuntes_ids
                                        count = count + 1
            else:
                apunte.saldo_acumulado = apunte.debit - apunte.credit

            if i == count and apunte.date < self.fecha_hasta:
                if apunte.saldo_acumulado > 0:
                    apunte.interes_generado = True
                    apuntes_calculados_ids.append(apunte.id)
                    fecha_inicial_str = str(apunte.date)
                    fecha_final_str = str(self.fecha_hasta)
                    if fecha_inicial_str and len(fecha_inicial_str) > 0 and fecha_inicial_str != "False":
                        if fecha_final_str and len(fecha_final_str) > 0 and fecha_final_str  != "False":
                            formato_fecha = "%Y-%m-%d"
                            fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
                            fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
                            diferencia = fecha_final - fecha_inicial

                            interes = apunte.saldo_acumulado * diferencia.days * self.tasa_interes / 30 / 100
                            # create move line
                            # Registro el monto de interes en la cuenta de ingreso

                            detalle = 'Intereses generados - '+ "${0:.2f}".format(apunte.saldo_acumulado)
                            detalle = detalle + ' x '+str(diferencia.days) + ' x ('+str(self.tasa_interes)+'% mensual)'

                            aml = {
                                'date': self.fecha_hasta,
                                'account_id': self.subcuenta_id.journal_id.cuenta_ganancia_id.id,
                                'name': detalle,
                                'partner_id': apunte.partner_id.id,
                                'credit': interes,
                            }

                            # create move line
                            # Acredito el monto de intereses a la cuenta del cliente
                            aml2 = {
                                'date': self.fecha_hasta,
                                'account_id': apunte.account_id.id,
                                'name': detalle,
                                'partner_id': apunte.partner_id.id,
                                'debit': interes,
                                'subcuenta_id': apunte.subcuenta_id.id,
                            }

                            line_ids = [(0, 0, aml), (0,0, aml2)]

                            # create move
                            move_name = "Intereses Generados/"
                            move = self.env['account.move'].create({
                                'name': move_name,
                                'date': self.fecha_hasta,
                                'journal_id': self.subcuenta_id.journal_id.id,
                                'state':'posted',
                                'company_id': company_id,
                                'partner_id': apunte.partner_id.id,
                                'line_ids': line_ids,
                            })
                            move_ids.append(move.id)
            apunte_previo = apuntes_ids[count-i]
            i = i + 1
        if move_ids != None:
            self.asientos_ids = move_ids

        if apuntes_calculados_ids != None:
            self.apuntes_calculados_ids = apuntes_calculados_ids
        return True

    @api.multi
    def generar_intereses_confirmar(self, cr):
        self.state = 'confirmado'
        asientos_ids = self.asientos_ids
        for asiento in asientos_ids:
            asiento.state = 'posted'
        return True


    @api.multi
    def generar_intereses_cancelar(self, cr):

        formulario_interes_ids = self.subcuenta_id.formulario_interes_ids
        formulario_pendiente = False
        if formulario_interes_ids != False:
            for formulario in formulario_interes_ids:
                if formulario.id > self.id and (formulario.state == 'confirmado' or formulario.state == 'pendiente' or formulario.state == 'borrador'):
                    formulario_pendiente = True
                    break

        if formulario_pendiente:
            raise ValidationError("Existen formulario/s pendiente, en borrador o confirmados posterior a este.")
        else:
            apuntes_ids = self.apuntes_calculados_ids
            for apunte in apuntes_ids:
                apunte.interes_generado = False

            if self.state == 'borrador':
                asientos_ids = self.asientos_ids
                for asiento in asientos_ids:
                    asiento.unlink()

            if self.state == 'confirmado':
                #Generar contra asientos
                moves_ids = []
                company_id = self.env['res.users'].browse(self.env.uid).company_id.id
                asientos_ids = self.asientos_ids
                for asiento in asientos_ids:
                    moves_ids.append(asiento.id)
                    if asiento is not None:
                        line_ids = []
                        for apunte in asiento.line_ids:
                            date = apunte.date
                            account_id = apunte.account_id.id
                            name = "Cancelo -" + apunte.name
                            partner_id = apunte.partner_id.id
                            credit = apunte.debit
                            debit = apunte.credit
                            subcuenta_id = apunte.subcuenta_id.id

                            aml = {
                                'date': date,
                                'account_id': account_id,
                                'name': name,
                                'partner_id': partner_id,
                                'credit': credit,
                                'debit': debit,
                                'subcuenta_id': subcuenta_id,
                            }

                            line_ids.append((0, 0, aml))

                        if line_ids != None:
                            # create move
                            move_name = "Cancelar - Intereses Generados/"
                            move = self.env['account.move'].create({
                                'name': move_name,
                                'date': asiento.date,
                                'journal_id': asiento.journal_id.id,
                                'state':'posted',
                                'company_id': company_id,
                                'partner_id': asiento.partner_id.id,
                                'line_ids': line_ids,
                            })
                            moves_ids.append(move.id)
                if moves_ids != None:
                    self.asientos_ids = moves_ids

            self.state = 'cancelado'
        return True

class subcuenta(osv.Model):
    _name = 'subcuenta'
    _description = 'subcuenta'
    _columns =  {
        'name': fields.char('Nombre', required=True),
        'subcuenta_id': fields.many2one('res.partner', 'Cliente'),
        'journal_id': fields.many2one('account.journal', 'Diario', required=True),
        'descuento_id': fields.many2one('descuento.de.cheques', 'Descuento'),
        'descuento_de_cheques': fields.boolean('Permite descuento de cheques'),
        'prestamos': fields.boolean('Permite prestamos'),
        'tasa_fija_descuento' : fields.float('Tasa Fija Descuento'),
        'tasa_mensual_descuento' : fields.float('Tasa Mensual Descuento'),
        'tasa_descubierto' : fields.float('Tasa Descubierto'),
        'apuntes_ids': fields.one2many('account.move.line', 'subcuenta_id', 'Apuntes'),
        'formulario_interes_ids': fields.one2many('formulario.interes', 'subcuenta_id', 'Intereses Auto Generados'),
        'state': fields.selection([('borrador', 'Borrador'), ('activa', 'Activa'), ('cancelada', 'Cancelada')], string='Estado', readonly=True),
        #faltan campos derivados
        #saldo
        'saldo' : fields.float('Saldo', compute="_calcular_saldo", readonly=True),
    }

    @api.one
    def activar(self, cr):
        _logger.error("Activar cuenta")
        self.state = 'activa'
    

    @api.multi
    def button_actualizar_saldo_acumulado(self, cr):
        apunte_previo = None
        apuntes_ids = self.apuntes_ids
        #self.env['subcuenta'].search([('subcuenta_id', '=', self.subcuenta_id)], limit=100),
        count = len(apuntes_ids)
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            if apunte_previo:
                apunte.saldo_acumulado = apunte.debit - apunte.credit + apunte_previo.saldo_acumulado
            else:
                apunte.saldo_acumulado = apunte.debit - apunte.credit
            apunte_previo = apunte
            i = i + 1

    @api.model
    def _actualizar_saldo_acumulado(self):
    	apunte_previo = None
    	apuntes_ids = self.apuntes_ids
    	count = len(apuntes_ids)
    	i = 1
    	while i <= count:
    		apunte = apuntes_ids[count-i]    		
    		if apunte_previo:
    			apunte.saldo_acumulado = apunte.debit - apunte.credit + apunte_previo.saldo_acumulado
    		else:
    			apunte.saldo_acumulado = apunte.debit - apunte.credit
    		apunte_previo = apunte
    		i = i + 1


    @api.one
    @api.depends('apuntes_ids')
    def _calcular_saldo(self):
		self.saldo = 0
		for apunte in self.apuntes_ids:
			self.saldo += apunte.debit - apunte.credit


    def ver_subcuentas(self, cr, uid, ids, context=None):
    	subcuentas_obj = self.pool.get('subcuentas')
    	subcuentas_ids = subcuentas_obj.search(cr, uid, [('active', '=', True)])
    	return {
    			'domain': "[('id', 'in', ["+','.join(map(str, subcuentas_ids))+"])]",
    			'name': ('Subcuentas'),
    			'view_type': 'form',
    			'view_mode': 'tree,form',
    			'res_model': 'subcuenta',
    			'view_id': False,
    			'type': 'ir.actions.act_window',
    			}

    _defaults = {
    	'state': 'borrador',
        'descuento_de_cheques': False,
        'prestamos': False,
        'saldo': 0,
    }
