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
    }

    _defaults = {
    	'interes_generado': False,
    }

#Add a new floats fields object res.partner
class res_partner(osv.Model):
    # This OpenERP object inherits from res.partner
    # toz add a subcuenta fields
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
        'journal_id': fields.many2one('account.journal', 'Diario', required=True),
        'descuento_id': fields.many2one('descuento.de.cheques', 'Descuento'),
        'active': fields.boolean('Activa'),
        'descuento_de_cheques': fields.boolean('Permite descuento de cheques'),
        'prestamos': fields.boolean('Permite prestamos'),
        'tasa_fija_descuento' : fields.float('Tasa Fija Descuento'),
        'tasa_mensual_descuento' : fields.float('Tasa Mensual Descuento'),
        'tasa_descubierto' : fields.float('Tasa Descubierto'),
        'apuntes_ids': fields.one2many('account.move.line', 'subcuenta_id', 'Apuntes'),
        #faltan campos derivados
        #saldo
        'saldo' : fields.float('Saldo', compute="_calcular_saldo", readonly=True),
    }

    @api.model
    def _actualizar_saldo_acumulado(self):
    	_logger.error("Actualizar Saldos")
    	apunte_previo = None
    	apuntes_ids = self.apuntes_ids #self.env['subcuenta'].search([('subcuenta_id', '=', self.subcuenta_id)], limit=100),
    	_logger.error("apuntes::: %r", apuntes_ids)
    	count = len(apuntes_ids)
    	i = 1
    	while i <= count:
    		apunte = apuntes_ids[count-i]
    		_logger.error("_FOR reconciled: %r", apunte.reconciled)
    		_logger.error("_FOR debit: %r", apunte.debit)
    		_logger.error("_FOR debit_cash_basis: %r", apunte.debit_cash_basis)
    		_logger.error("_FOR credit: %r", apunte.credit)
    		_logger.error("_FOR credit_cash_basis: %r", apunte.credit_cash_basis)
    		_logger.error("_FOR balance: %r", apunte.balance)
    		_logger.error("_FOR balance_cash_basis: %r", apunte.balance_cash_basis)
    		_logger.error("_FOR amount_currency: %r", apunte.amount_currency)
    		_logger.error("_FOR amount_residual: %r", apunte.amount_residual)
    		_logger.error("_FOR amount_residual_currency: %r", apunte.amount_residual_currency)
    		
    		if apunte_previo:
    			#_logger.error("_apunte.saldo: debito %r, credito %r", apunte.debit, apunte.credit)
    			apunte.saldo_acumulado = apunte.debit - apunte.credit + apunte_previo.saldo_acumulado
    		else:
    			#_logger.error("_FIrst: debito %r, credito %r", apunte.debit, apunte.credit)
    			apunte.saldo_acumulado = apunte.debit - apunte.credit
    		apunte_previo = apunte
    		i = i + 1
    		_logger.error("****************************************************")

    @api.multi
    def algo(self, cr):
        _logger.error("algooooooooooooooooooooooooooooooooooooooooooooooooooooo")
        for apunte in self.apuntes_ids:
            apunte.interes_generado = False

        return True
    
    @api.multi
    def algo2(self, cr):
        _logger.error("22222222222222222222222222222222")
        apunte_previo = None
        apuntes_ids = self.apuntes_ids
        _logger.error("caclular_intereses apuntes::: %r", apuntes_ids)
        count = len(apuntes_ids)
        i = 1
        while i <= count:
            apunte = apuntes_ids[count-i]
            _logger.error("FOR apuntes_actual: %r", apunte)
            #_logger.error("FOR Apunte actual: debe %r - haber: %r", apunte.debit, apunte.credit)
            #_logger.error("Apunte previo: %r", apunte_previo)
            if apunte_previo is not None:
                apunte.saldo_acumulado = apunte.debit - apunte.credit + apunte_previo.saldo_acumulado
                ##_logger.error("FOR saldo acumulado = debe: %r - haber: %r + acum: %r", apunte.debit, apunte.credit, apunte_previo.saldo_acumulado)
                fechas_bool = apunte_previo.date != apunte.date
                #_logger.error("if-- fechas: previa: %r < %r (final) result: %r", apunte_previo.date, apunte.date, fechas_bool)
                if fechas_bool:
                    #Cambio de fecha, posible generacion de asiento contable
                    ##_logger.error("#Cambio de fecha, posible generacion de asiento contable")
                    if apunte_previo.saldo_acumulado > 0:
                        #Saldo deudor en cuenta y cambio de fecha => calcular intereses
                        ##_logger.error("#Saldo deudor en cuenta y cambio de fecha => calcular intereses")
                        ##_logger.error("#apunte previo.interes_generado %r == False__", apunte_previo.interes_generado)
                        if apunte_previo.interes_generado == False:
                            fecha_inicial_str = str(apunte_previo.date)
                            fecha_final_str = str(apunte.date)
                            if fecha_inicial_str and len(fecha_inicial_str) > 0 and fecha_inicial_str != "False":
                                if fecha_final_str and len(fecha_final_str) > 0 and fecha_final_str  != "False":
                                    formato_fecha = "%Y-%m-%d"
                                    fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
                                    fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
                                    diferencia = fecha_final - fecha_inicial
                                    
                                    interes = apunte_previo.saldo_acumulado * diferencia.days * self.tasa_descubierto / 30 / 100
                                    _logger.error("interes: %r", interes)
                                    company_id = self.env['res.users'].browse(self.env.uid).company_id.id
                                    
                                    # create move line
                                    # Registro el monto de interes en la cuenta de ingreso
                                    
                                    aml = {
                                        'date': apunte.date,
                                        'account_id': self.journal_id.cuenta_ganancia_id.id,
                                        'name': 'Intereses generados',
                                        'partner_id': apunte.partner_id.id,
                                        'credit': interes,
                                    }

                                    # create move line
                                    # Acredito el monto de intereses a la cuenta del cliente
                                    aml2 = {
                                        'date': apunte.date,
                                        'account_id': apunte.account_id.id,
                                        'name': 'Intereses generados',
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
                                        'journal_id': self.journal_id.id,
                                        'state':'draft',
                                        'company_id': company_id,
                                        'partner_id': apunte.partner_id.id,
                                        'line_ids': line_ids,
                                    })
                                    #move.state = 'posted'
                                    apuntes_ids = self.apuntes_ids
                                    count = count + 1
                        apunte_previo.interes_generado = True
                    else:
                        #Saldo acreedor, no es necesario calcular intereses
                        apunte_previo.interes_generado = True
            else:
                apunte.saldo_acumulado = apunte.debit - apunte.credit
            apunte_previo = apuntes_ids[count-i]
            _logger.error("FOR apunte_previo: %r", apunte_previo)
            i = i + 1
        return True

    @api.one
    def _calcular_intereses(self, cr):
		apunte_previo = None
		apuntes_ids = self.apuntes_ids
		_logger.error("caclular_intereses apuntes::: %r", apuntes_ids)
		count = len(apuntes_ids)
		i = 1
		while i <= count:
			apunte = apuntes_ids[count-i]
			if apunte_previo:
				if apunte_previo.date < apunte.date:
    				#Cambio de fecha, posible generacion de asiento contable
					_logger.error("#Cambio de fecha, posible generacion de asiento contable")
					if apunte_previo.saldo_acumulado > 0:
    					#Saldo deudor en cuenta y cambio de fecha => calcular intereses
						_logger.error("#Saldo deudor en cuenta y cambio de fecha => calcular intereses")
						if apunte_previo.interes_generado == False:
							fecha_inicial_str = str(apunte_previo.date)
							fecha_final_str = str(apunte.date)
							if fecha_inicial_str and len(fecha_inicial_str) > 0 and fecha_inicial_str != "False":
								if fecha_final_str and len(fecha_final_str) > 0 and fecha_final_str  != "False":
									formato_fecha = "%Y-%m-%d"
									fecha_inicial = datetime.strptime(fecha_inicial_str, formato_fecha)
									fecha_final = datetime.strptime(fecha_final_str, formato_fecha)
									diferencia = fecha_final - fecha_inicial
									
									interes = apunte_previo.saldo_acumulado * diferencia.days * self.tasa_descubierto / 30 / 100
									_logger.error("interes: %r", interes)
									company_id = self.env['res.users'].browse(self.env.uid).company_id.id
									
									# create move line
									# Registro el monto de interes en la cuenta de ingreso
									
									aml = {
										'date': apunte.date,
										'account_id': self.journal_id.cuenta_ganancia_id.id,
										'name': 'Intereses generados',
										'partner_id': apunte.partner_id.id,
										'credit': interes,
									}

							        # create move line
							        # Acredito el monto de intereses a la cuenta del cliente
							        aml2 = {
							            'date': apunte.date,
							            'account_id': apunte.account_id,
							            'name': 'Intereses generados',
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
							            'journal_id': self.journal_id.id,
							            'state':'draft',
							            'company_id': company_id,
							            'partner_id': apunte.partner_id.id,
							            'line_ids': line_ids,
							        })
							        move.state = 'posted'
							        apuntes_ids = self.apuntes_ids
							        count = count + 2
						apunte_previo.interes_generado = True
					else:
						#Saldo acreedor, no es necesario calcular intereses
						apunte_previo.interes_generado = True
    		i = i + 1
		return True


    @api.one
    @api.depends('apuntes_ids')
    def _calcular_saldo(self):
   		_logger.error("Calcular Saldo")
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
    	'active': True,
        'descuento_de_cheques': False,
        'prestamos': False,
        'saldo': 0,
    }