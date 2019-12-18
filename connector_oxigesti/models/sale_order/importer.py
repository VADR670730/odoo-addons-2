# Copyright NuoBiT Solutions, S.L. (<https://www.nuobit.com>)
# Eric Antones <eantones@nuobit.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import re

from odoo import _

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import (
    mapping, external_to_m2o, only_create)


class SaleOrderBatchImporter(Component):
    """ Import the Oxigesti Services.

    For every sale order in the list, a delayed job is created.
    """
    _name = 'oxigesti.sale.order.delayed.batch.importer'
    _inherit = 'oxigesti.delayed.batch.importer'

    _apply_on = 'oxigesti.sale.order'


class SaleOrderImporter(Component):
    _name = 'oxigesti.sale.order.importer'
    _inherit = 'oxigesti.importer'

    _apply_on = 'oxigesti.sale.order'

    def _must_skip(self, binding):
        if not binding:
            return None

        order = self.component(usage='binder').unwrap_binding(binding)
        if order.state != 'draft':
            state_option = dict(
                order.fields_get(['state'], ['selection'])
                    .get('state').get('selection'))

            return _('The Order %s is %s -> Update not allowed' % (order.name, state_option[order.state]))

        return None

    def _import_dependencies(self):
        # customer
        external_id = (self.external_data['Cliente'],)
        self._import_dependency(external_id, 'oxigesti.res.partner', always=False)

        # products
        adapter = self.component(usage='backend.adapter',
                                 model_name='oxigesti.sale.order.line')
        oxigesti_cargos_servicio = adapter.search(filters=[
            ('Codigo_Servicio', '=', self.external_data['Codigo_Servicio']),
        ])
        oxigesti_idarticulos = [str(adapter.id2dict(x)['Articulo'])
                                for x in oxigesti_cargos_servicio]

        exporter = self.component(usage='direct.batch.exporter',
                                  model_name='oxigesti.product.product')
        exporter.run(domain=[
            ('company_id', '=', self.backend_record.company_id.id),
            ('default_code', 'in', oxigesti_idarticulos),
        ])

    def _after_import(self, binding):
        ## rebind the lines, for the sync date
        binder = self.binder_for('oxigesti.sale.order.line')
        for line in binding.oxigesti_order_line_ids:
            binder.bind(line.external_id, line)

        ## order validation
        binder = self.component(usage='binder')
        sale_order = binder.unwrap_binding(binding)
        sale_order.onchange_partner_id()
        for line in sale_order.order_line:
            line.product_id_change()
        sale_order.action_confirm()
        sale_order.action_done()

        ## picking validation
        binder = self.binder_for('oxigesti.sale.order.line')
        adapter = self.component(usage='backend.adapter',
                                 model_name='oxigesti.sale.order.line')
        picking_id = None
        for order_line_id in binding.oxigesti_order_line_ids.filtered(lambda x: x.move_ids):
            if len(order_line_id.move_ids) > 1:
                raise AssertionError("The order line '%s' has more than one move lines. "
                                     "It should be exactly 1. " % (order_line_id,))
            move_id = order_line_id.move_ids
            if move_id.move_line_ids:
                raise AssertionError("The movement '%s' already has lines. "
                                     "It should be empty before inserting the new data" % (move_id,))
            if not picking_id:
                picking_id = move_id.picking_id
            else:
                if picking_id != move_id.picking_id:
                    raise Exception("Unexpected error! The same order contains lines "
                                    "belonging to a different picking '%s' and '%s'" % (
                                        picking_id.name, move_id.picking_id.name
                                    ))
            move_line_id_d = {
                'product_id': move_id.product_id.id,
                'location_id': move_id.location_id.id,
                'location_dest_id': move_id.location_dest_id.id,
                'qty_done': move_id.product_uom_qty,
                'product_uom_id': move_id.product_uom.id,
                'picking_id': picking_id.id,
            }
            external_id = binder.to_external(order_line_id)
            tracking_name = adapter.id2dict(external_id)['Partida']
            if tracking_name:
                Lot = self.env['stock.production.lot']
                lot_id = Lot.search([
                    ('company_id', '=', self.backend_record.company_id.id),
                    ('product_id', '=', move_id.product_id.id),
                    ('name', '=', tracking_name),
                ])
                if not lot_id:
                    lot_id = Lot.create({
                        'company_id': self.backend_record.company_id.id,
                        'product_id': move_id.product_id.id,
                        'name': tracking_name,
                    })
                move_line_id_d.update({
                    'lot_id': lot_id.id,
                })
            move_id.move_line_ids = [(0, False, move_line_id_d)]

        picking_id.button_validate()