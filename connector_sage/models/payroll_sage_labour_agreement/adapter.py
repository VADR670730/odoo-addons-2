# Copyright NuoBiT Solutions, S.L. (<https://www.nuobit.com>)
# Eric Antones <eantones@nuobit.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import models, fields

from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job


class PayrollSageLabourAgreementAdapter(Component):
    _name = 'sage.payroll.sage.labour.agreement.adapter'
    _inherit = 'sage.adapter'
    _apply_on = 'sage.payroll.sage.labour.agreement'

    _sql = """select c.CodigoEmpresa, n.CodigoConvenio, n.Convenio, n.FechaRegistroCV, n.FechaFinalNom, 
                     n.FechaRevision, n.CodigoConvenioColectivo, n.CodigoConvenioColectivoAnt,
                     n.JornadaAnual, n.ConvenioBloqueado
              from (select distinct c.CodigoEmpresa, c.CodigoConvenio, c.FechaRegistroCV
                    from %(schema)s.ConvenioConcepto c
                    where exists (
                             select 1
                             from %(schema)s.Convenio n
                             where c.CodigoConvenio = n.CodigoConvenio and 
                                   c.FechaRegistroCV = n.FechaRegistroCV
                          )
                   ) c, %(schema)s.Convenio n
              where c.CodigoConvenio = n.CodigoConvenio and 
                    c.FechaRegistroCV = n.FechaRegistroCV
     """
    _id = ('CodigoEmpresa', 'CodigoConvenio', 'FechaRegistroCV')

