# -*- coding: utf-8 -*-
#/#############################################################################
#
#   Odoo, Open Source Management Solution
#   Copyright (C) 2015 NuoBiT Solutions, S.L. (<http://www.nuobit.com>).
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of the
#   License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#/#############################################################################



from datetime import timedelta

import pytz

import base64
import StringIO
import re
import csv
import unicodedata
import string

import decimal

from openerp import models, fields, api, _
from openerp.exceptions import AccessError, Warning, ValidationError

from openerp.addons.product.product import check_ean



import logging

_logger = logging.getLogger(__name__)



class import_header(models.Model):
    """Session"""
    _name = 'epe.header'
    _description = 'Header'

    name = fields.Char(string='Description', required=False,
        readonly=False)

    date_import = fields.Datetime('Date', required=True, default=fields.datetime.now())

    supplier_id = fields.Many2one('res.partner', string="Supplier", domain=[('supplier','=', True)])

    delimiter = fields.Char(string='Delimitar', required=True,
        readonly=False, default=',')
    quotechar = fields.Char(string='Quotechar', required=True,
        readonly=False, default='"')

    strip_fields = fields.Boolean(string='Strip values',
        help="Remove trail and leading spaces of each field",
        readonly=False, default=True)

    round_numeric_fields = fields.Integer(string='Round',
        help="Round numeric values to this number of decimals. -1 or any negative number to not round at all",
        readonly=False, required=True, default=2)


    update_name = fields.Boolean(string='Update Description',
        help="Update Description when importing data",
        readonly=False, default=False)

    update_ean13 = fields.Boolean(string='Update EAN',
        help="Update EAN 13 when importing data",
        readonly=False, default=False)

    update_saleprice = fields.Boolean(string='Update Sale Price',
        help="Update Sale Pricelist when importing data",
        readonly=False, default=False)

    update_purchaseprice = fields.Boolean(string='Update Purchase Price',
        help="Update Purchase Pricelist when importing data",
        readonly=False, default=True)

    update_category = fields.Boolean(string='Update Category',
        help="Update Category if exists",
        readonly=False, default=False)


    create_product = fields.Boolean(string='Create Product',
        help="Create Product if not exists",
        readonly=False, default=False)

    create_category_onupdate = fields.Boolean(string='Create Category',
        help="If 'Update Category' is selected create Category if not exists. If 'Update Category' is not selected it has no effect",
        readonly=False, default=False)

    create_category_oncreate = fields.Boolean(string='Create Category',
        help="Create Category if not exists",
        readonly=False, default=False)

    create_always_supplier = fields.Boolean(string='Create always Supplier Info',
        help="Create Supplier Info although Purchase Pricelist is null",
        readonly=False, default=False)

    create_without_supplier = fields.Boolean(string='Create without Supplier Info',
        help="Allows to create a Product without Supplier Info and without Purchase Pricelist",
        readonly=False, default=False)


    sale_delay = fields.Float(string='Customer Lead Time', required=True,
        readonly=False, default=0)

    purchase_delay = fields.Float(string='Delivery Lead Time', required=True,
        readonly=False, default=0)

    product_type = fields.Selection([('product', 'Stockable Product'), ('consu', 'Consumable'), ('service', 'Service')],
        'Product Type', required=True, default='product',
        help="Consumable: Will not imply stock management for this product. \nStockable product: Will imply stock management for this product.")

    cost_method = fields.Selection(type='selection', selection=[('standard', 'Standard Price'), ('average', 'Average Price'), ('real', 'Real Price')],
            help="Standard Price: The cost price is manually updated at the end of a specific period (usually every year).\nAverage Price: The cost price is recomputed at each incoming shipment and used for the product valuation.\nReal Price: The cost price displayed is the price of the last outgoing product (will be use in case of inventory loss for example).",
            string="Costing Method", required=True, copy=True, default='average')

    lst_price = fields.Float(string='Sale Price',
        readonly=False, required=True, default=0)



    map1_default_code = fields.Many2one('epe.header.field', string='Reference')
    map2_name = fields.Many2one('epe.header.field', string='Description')
    map3_category = fields.Many2one('epe.header.field', string='Category')
    map4_ean13 = fields.Many2one('epe.header.field', string='EAN')
    map5_pricelist_sale = fields.Many2one('epe.header.field', string='Sale Pricelist')
    map6_pricelist_purchase = fields.Many2one('epe.header.field', string='Purchase Pricelist')

    field_ids = fields.One2many('epe.header.field', 'header_id')


    datas = fields.Binary('File')
    datas_fname = fields.Char(string='Filename')

    line_ids = fields.One2many('epe.line','header_id')


    def _get_map_fields(self):
        # obtenim els cmaps de mapping
        mapi = []
        for f in self.fields_get().keys():
            m = re.match('map([0-9]+)_(.+)$', f)
            if m is not None:
                mapi.append((f, m.group(2), int(m.group(1)), self[f] ))
        mapi.sort(key=lambda x: x[2])

        return mapi


    def _split_line(self, line):
        line9 = []
        for line in csv.reader([line],delimiter=self.delimiter.encode(), quotechar=self.quotechar.encode()):
            line9.append(line)
        return line9[0]


    @api.multi
    def load_header(self):
        #esborem totes le linies
        self.line_ids.unlink()

        # esborrem les dades dels desplegables
        #self.env['epe.header.field'].search([('header_id', '=', self.id)]).unlink()
        self.field_ids.unlink()

        txt = base64.decodestring(self.datas)
        # remove lasts newlines
        txt = re.sub(r'\n*$','' ,txt,flags=re.DOTALL)

        # read the file headers
        for i, line in enumerate(txt.split('\n')):
            field_values = [x.strip() if self.strip_fields else x for x in self._split_line(line)]
            if i==0:
                header = field_values

        # populate field combox sorted by position
        mapi = self._get_map_fields()
        for f in header:
            ehf = self.env['epe.header.field'].create({'header_id': self.id, 'name': f })
            #ehf = self.field_ids.create({'name': f, 'header_id': self.id})
            if mapi!=[]:
                fc, ff, _, _ = mapi.pop(0)
                self[fc] = ehf



    @api.multi
    def load_data(self):
        #esborem totes le linies
        self.line_ids.unlink()

        txt = base64.decodestring(self.datas)
        # remove lasts newlines
        txt = re.sub(r'\n*$','' ,txt,flags=re.DOTALL)

        mapi = dict(map(lambda x: (x[1], x[3].name), self._get_map_fields()))

       # read the file headers
        for i, line in enumerate(txt.split('\n')):
            field_values = [x.strip() if self.strip_fields else x for x in self._split_line(line)]
            if i==0:
                header = field_values
            else:
                if len(header)!=len(field_values):
                    raise Warning(_("Incorrect field number in line %i") % i+1)
                field_values = [x if x!='' else None for x in field_values]
                fields_file = dict(zip(header, field_values))
                fields = {'header_id': self.id}
                for k, v in mapi.items():
                    if v:
                        fields[k]=fields_file[v]
                self.env['epe.line'].create(fields)
                #self.line_ids.create(fields)


    @api.multi
    def clear(self):
        self.line_ids.unlink()

    @api.multi
    def remove_done(self):
        self.line.search([('status', '=', 'done')]).unlink()
        #for line in self.line_ids:
        #    if line.status == 'done':
        #        line.unlink()




    def _check_float_format(self, r):
        v = None

        if re.search('^[0-9]+$', r) is not None:
            v = r
        if re.search('^[0-9]+,[0-9]+$', r) is not None:
            v = r.replace(',','.')
        elif re.search('^[0-9]+\.[0-9]+$', r) is not None:
            v = r
        elif re.search('^[0-9]+\.[0-9]+,[0-9]+$', r) is not None:
            v = r.replace('.','').replace(',','.')
        elif re.search('^[0-9]+,[0-9]+\.[0-9]+$', r) is not None:
            v = r.replace(',','')

        return v

    def _format_decimal(self, d, ret_type='float'):
        f = decimal.Decimal(d)
        if self.round_numeric_fields:
            f = decimal.Decimal(f.quantize(decimal.Decimal('0.%s1' % '0'* (self.round_numeric_fields-1)), rounding=decimal.ROUND_HALF_EVEN))
        if ret_type=='text':
            f=str(f)
        elif ret_type=='float':
            float(f)
        return f

    def _float2decimal(self, d):
        return decimal.Decimal(d).quantize(decimal.Decimal('0.00000000001'))

    def _equal(self, a, b):
        # a, b: str represenitng decimal
        a0 = self._float2decimal(a)
        b0 = self._float2decimal(b)
        return a0==b0


    def _slugify(self, r):
        return ''.join(x for x in unicodedata.normalize('NFKD', r) if x in string.ascii_letters).lower()



    def _get_cat(self, category):
        status = None
        cat, msg = None, False
        nc = []
        for cat in self.env['product.category'].search([]):
            if self._slugify(cat.name)==self._slugify(category):
                nc.append(cat)
        if len(nc)==0:
            cat_langs = self.env['ir.translation'].search([('lang','!=', self._context['lang']),
                ('name', '=', 'product.category,name')])

            nl = []
            src_d = {}
            for cl in cat_langs:
                if self._slugify(cl.value)==self._slugify(category):
                    nl.append(cl)

                if cl.res_id not in src_d:
                    src_d[cl.res_id]=[cl.src, cl.lang=='en_US']
                else:
                    if src_d[cl.res_id][0]!=cl.src:
                        status='error'
                        msg=_("There's more than one translation sources with different source id: %i, src0: '%s', src1: %s" % (cl.res_id, src_d[cl.res_id], cl.src))
                    else:
                        src_d[cl.res_id][1]|=(cl.lang=='en_US')

            if len(nl)==0:
                nls = set(map(lambda x: x[0], filter(lambda x: not x[1], src_d.values())))
                for src in nls:
                    if self._slugify(src)==self._slugify(category):
                        status='error'
                        msg =_("Exists an english source with the Category but explicit english language is not defined")

                msg=_('Category did not exist, it was created')
                status = 'create'
            else:
                nll = ','.join(["%s: %s" % (x.lang, x.value) for x in nl])
                status='error'
                msg=_("Current language '%s' does not have that Category but other languages do: [%s]") % (self._context['lang'], nll )

        elif len(nc)==1:
            if self._slugify(nc[0].name)!=self._slugify(category):
                msg = _("Used category %s instead of %s") % (nc[0].name, category)
            status = 'exists'
            cat = nc[0]
        else:
            status = 'error'
            msg=_("There's more than one category with the same slug %s") % nc

        return status, cat, msg


    '''
    @api.onchange('show_status')
    #@api.multi
    def onchange_status(self):
        fs1 = self.line_ids.filtered(lambda x: x.status==self.show_status).mapped('id')
        res = {'line_ids': [('id', 'in', fs1)]}

        return dict(domain=res)
    '''

    @api.multi
    def update(self):
        n = len(self.line_ids)
        pco = None
        for i, line in enumerate(self.line_ids):
            if n!=1:
                pc = float(i)/(float(n)-1)*100.0
            else:
                pc = 100.0
            if int(pc)!=pco:
                #if (int(pc) % 10) == 0:
                _logger.info('Import progress %.2f%% (%i/%i)' % (pc, i+1, n))
            pco = int(pc)

            if line.status=='done':
                continue

            line.status = False
            line.observations = False

            # check if product exists (defualt_code)
            if not line.default_code:
                line.status='error'
                line.observations=_("Reference cannot be null")
                continue

            product = {}
            pp = self.env['product.product'].search([('default_code','=', line.default_code)])
            if len(pp)>1:
                line.status='error'
                line.observations=_("There's more than one product with the same Reference")
                continue
            else:
                product['status'] = 'update' if len(pp)==1 else 'create'

            # check pricelist_sale
            if line.pricelist_sale:
                price = self._check_float_format(line.pricelist_sale)
                if price is None:
                    line.status='error'
                    line.observations=_('Unknown float format')
                    continue
                else:
                    line.pricelist_sale = self._format_decimal(price, ret_type='text')

            # check purchase priceist
            if line.pricelist_purchase:
                price = self._check_float_format(line.pricelist_purchase)
                if price is None:
                    line.status='error'
                    line.observations=_('Unknown float format')
                    continue
                else:
                    line.pricelist_purchase = self._format_decimal(price, ret_type='text')

            ## populate data
            product['data'] = {}
            if product['status'] == 'update':
                product['object'] = pp

                if self.update_name:
                    if line.name:
                        if pp.name!=pp.name:
                            product['data'].update({'name': line.name })
                        # TODO: Update name on every language
                    else:
                        line.status='error'
                        line.observations=_('Description cannot be null')
                        continue

                if self.update_category:
                    if line.category:
                        status, cat, msg = self._get_cat(line.category)
                        if status=='error':
                            line.status = status
                            line.observations = msg
                            continue
                        if status == 'exists':
                            line.category = cat.name
                            if pp.categ_id!=cat.id:
                                product['data'].update({'categ_id': cat.id})
                                line.observations = msg
                        else:
                            if self.create_category_onupdate:
                                product['category']={'status': 'create', 'data': {'name': line.category}}
                                line.observations = msg
                            else:
                                line.status = 'error'
                                line.observations=_('Category did not exist. Enable "Create Category" on update options to create it')
                                continue
                    else:
                        line.status='error'
                        line.observations=_('Category cannot be null')
                        continue

                if self.update_ean13:
                    if line.ean13:
                        if pp.ean13!=line.ean13:
                            if check_ean(line.ean13):
                                product['data'].update({'ean13': line.ean13 })
                            else:
                                line.status='error'
                                line.observations=_('Invalid "EAN13 Barcode"')
                                continue
                    else:
                        line.status='error'
                        line.observations=_('"EAN13 Barcode" cannot be null')
                        continue

                if self.update_saleprice:
                    if line.pricelist_sale:
                        pricelist_sale = float(line.pricelist_sale)
                        if not self._equal(pp.lst_price, pricelist_sale):
                            product['data'].update({'lst_price': pricelist_sale })
                    else:
                        line.status='error'
                        line.observations=_('Sale Price cannot be null')
                        continue


                if self.update_purchaseprice:
                    if line.pricelist_purchase:
                        if not self.supplier_id.id:
                            line.status='error'
                            line.observations=_('If there is a Purchase Pricelist the Supplier cannot be null')
                            continue
                        else:
                            suppinfo = pp.seller_ids.filtered(lambda x: x.name==self.supplier_id)
                            if len(suppinfo)>1:
                                line.status='error'
                                line.observations=_('There is more then one Supplier defined')
                                continue
                            elif len(suppinfo)==0:
                                product['data'].update({'seller_ids': [(0,_, {'name': self.supplier_id.id, 'delay': self.purchase_delay,
                                                                          'pricelist_ids': [(0,_,{'min_quantity': 0,
                                                                                                  'price': float(line.pricelist_purchase)})]})]})
                            else:
                                plist = suppinfo.pricelist_ids
                                if len(plist)>1:
                                    plist0 = plist.filtered(lambda x: x.min_quantity==0)
                                    line.status='error'
                                    line.observations=_('There is more than one Purchase Pricelist')
                                    if len(plist0)==0:
                                        line.observations+=_(' and none has quantity=0')
                                    elif len(plist0)==1:
                                        line.observations=_(' and just one has quantity=0')
                                    else:
                                        line.observations=_(' and more than one has quantity=0')
                                    continue
                                elif len(plist)==0:
                                    product['data'].update({'seller_ids': [(1, suppinfo.id, {
                                                                          'pricelist_ids': [(0,_,{'min_quantity': 0,
                                                                                                  'price': float(line.pricelist_purchase)})]})]})
                                else:
                                    pricelist_purchase = float(line.pricelist_purchase)
                                    old_pricelist_purchase = pp.seller_ids.filtered(lambda x: x.id==suppinfo.id).mapped('pricelist_ids').filtered(lambda x: x.id==plist.id).price
                                    if not self._equal(old_pricelist_purchase, pricelist_purchase):
                                        product['data'].update({'seller_ids': [(1, suppinfo.id, {
                                                                          'pricelist_ids': [(1, plist.id, {'price': pricelist_purchase})]})]})
                    else:
                        line.status='error'
                        line.observations=_('Purchase Price cannot be null')
                        continue

            else: #### Create product
                if not self.create_product:
                    line.status = 'pending'
                    line.observations = _("Product does not exist. Enable 'Create Product' to create it")
                    continue

                product['data'].update({'default_code': line.default_code,
                                        'sale_delay': self.sale_delay, 'type': self.product_type,
                                        'cost_method': self.cost_method })

                if line.name:
                    product['data'].update({'name': line.name})
                else:
                    line.status='error'
                    line.observations=_('Description cannot be null')
                    continue

                if line.category:
                    status, cat, msg = self._get_cat(line.category)
                    if status=='error':
                        line.status = status
                        line.observations = msg
                        continue
                    if status == 'exists':
                        line.category = cat.name
                        product['data'].update({'categ_id': cat.id})
                        line.observations = msg
                    else:
                        if self.create_category_oncreate:
                            product['category']={'status': 'create', 'data': {'name': line.category}}
                            line.observations = msg
                        else:
                            line.status = 'error'
                            line.observations=_('Category did not exist. Enable "Create Category" on create options to create it')
                            continue
                else:
                    line.status='error'
                    line.observations=_('Category cannot be null')
                    continue

                if line.ean13:
                    if check_ean(line.ean13):
                        product['data'].update({'ean13': line.ean13 })
                    else:
                        line.status='error'
                        line.observations=_('Invalid "EAN13 Barcode"')
                        continue

                if line.pricelist_sale:
                    product['data'].update({'lst_price': float(line.pricelist_sale) })
                else:
                    product['data'].update({'lst_price': self.lst_price })

                if line.pricelist_purchase:
                    if not self.supplier_id.id:
                        line.status='error'
                        line.observations=_('If there is a Purchase Pricelist the Supplier cannot be null')
                        continue
                    else:
                        product['data'].update({'seller_ids': [(0, _, {'name': self.supplier_id.id, 'delay': self.purchase_delay,
                                                                      'pricelist_ids': [(0, _, {'min_quantity': 0,
                                                                                              'price': float(line.pricelist_purchase)})]})]})
                else:
                    if self.supplier_id.id:
                        if self.create_always_supplier:
                            product['data'].update({'seller_ids': [(0, _, {'name': self.supplier_id.id, 'delay': self.purchase_delay })]})
                        else:
                            line.status='error'
                            line.observations=_("There is no Purchase Pricelist. Enable 'Create always Supplier Info' to force the creation of a product with Supplier and without Purchase Pricelist")
                            continue
                    else:
                        if not self.create_without_supplier:
                            line.status='error'
                            line.observations=_("There is no Purchase Pricelist and there is no Supplier selected. Enable 'Create without Supplier Info' to force the creation of a product without Supplier and Purchase Pricelist")
                            continue



            ## save data
            cat = None
            if product.get('category') is not None:
                if product['category']['status']=='create':
                    cat = self.env['product.category'].create(product['category']['data'])
                    product['data'].update({'categ_id': cat.id})

            if product['status']=='update':
                if product['data'] != {}:
                    product['object'].write(product['data'])
                else:
                    line.observations = _("Nothing changed. Data already updated")
            else:
                self.env['product.product'].create(product['data'])

            line.status = 'done'








    '''
    def import_file(self, cr, uid, ids, context=None):
    fileobj = TemporaryFile('w+')
    fileobj.write(base64.decodestring(data))

    # your treatment
    return
    '''
    '''
        if context is None:
            context = {}
        result = {}
        bin_size = context.get('bin_size')
        for attach in self.browse(cr, uid, ids, context=context):
            if attach.store_fname:
                result[attach.id] = self._file_read(cr, uid, attach.store_fname, bin_size)
            else:
                result[attach.id] = attach.db_datas
        return result

    def _file_read(self, cr, uid, fname, bin_size=False):
        full_path = self._full_path(cr, uid, fname)
        r = ''
        try:
            if bin_size:
                r = os.path.getsize(full_path)
            else:
                r = open(full_path,'rb').read().encode('base64')
        except IOError:
            _logger.exception("_read_file reading %s", full_path)
        return r

    def _data_set(self, cr, uid, id, name, value, arg, context=None):
        # We dont handle setting data to null
        if not value:
            return True
        if context is None:
            context = {}
        location = self._storage(cr, uid, context)
        file_size = len(value.decode('base64'))
        attach = self.browse(cr, uid, id, context=context)
        fname_to_delete = attach.store_fname
        if location != 'db':
            fname = self._file_write(cr, uid, value)
            # SUPERUSER_ID as probably don't have write access, trigger during create
            super(ir_attachment, self).write(cr, SUPERUSER_ID, [id], {'store_fname': fname, 'file_size': file_size, 'db_datas': False}, context=context)
        else:
            super(ir_attachment, self).write(cr, SUPERUSER_ID, [id], {'db_datas': value, 'file_size': file_size, 'store_fname': False}, context=context)

        # After de-referencing the file in the database, check whether we need
        # to garbage-collect it on the filesystem
        if fname_to_delete:
            self._file_delete(cr, uid, fname_to_delete)
        return True
    '''

class import_header_field(models.Model):
    """Session"""
    _name = 'epe.header.field'
    _description = 'Import Field'

    name = fields.Char(string='Description', required=True,
        readonly=False)

    header_id = fields.Many2one('epe.header', required=True, ondelete="cascade")

class import_lines(models.Model):
    """Session"""
    _name = 'epe.line'
    _description = 'Import Lines'

    default_code = fields.Char(string='Reference', required=True)

    name = fields.Char(string='Description', required=False,
        readonly=False)

    category = fields.Char(string='Category', required=False,
        readonly=False)

    ean13 = fields.Char(string='EAN', required=False,
        readonly=False)

    pricelist_sale = fields.Char(string="Sale Pricelist", required=False)
    pricelist_purchase = fields.Char(string="Purchase Pricelist", required=False)

    header_id = fields.Many2one('epe.header', required=True, ondelete="cascade")

    status = fields.Selection([('done',_('Done')),('error',_('Error')), ('pending', _('Pending'))], string="Status")
    observations = fields.Text(string='Observations',
        readonly=True)





