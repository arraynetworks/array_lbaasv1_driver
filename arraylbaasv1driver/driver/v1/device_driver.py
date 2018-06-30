# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 Array Networks, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Array Networks, Inc.

import netaddr
import time

from oslo.config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from neutron.api.v2 import attributes
from neutron.plugins.common import constants

from neutron_lbaas.db.loadbalancer import loadbalancer_db
from neutron_lbaas.services.loadbalancer.drivers import abstract_driver

from arraylbaasv1driver.driver.v1 import db

LOG = logging.getLogger(__name__)
DRIVER_NAME = 'ArrayAPV'

OPTS = [
    cfg.StrOpt(
        'array_management_ip',
        default='192.168.0.200',
        help=("APV IP Addresses")
    ),
    cfg.StrOpt(
        'array_interfaces',
        default='port2',
        help=('APV interfaces')
    ),
    cfg.StrOpt(
        'array_api_user',
        default='restful',
        help=('APV Restful API user')
    ),
    cfg.StrOpt(
        'array_api_password',
        default='click1',
        help=('APV Restful API password')
    ),
    cfg.StrOpt(
        'array_device_driver',
        default=('arraylbaasv1driver.driver.v1.avx_driver.'
                 'ArrayAVXAPIDriver'),
        help=('The driver used to provision ADC product')
    )
]

cfg.CONF.register_opts(OPTS, 'arraynetworks')


class ArrayADCDriver(abstract_driver.LoadBalancerAbstractDriver):

    def __init__(self, plugin):
        LOG.debug("ArrayApvDriver __init__")
        self.plugin = plugin

        self.hosts = cfg.CONF.arraynetworks.array_management_ip.split(',')[0:2]
        self.interfaces = cfg.CONF.arraynetworks.array_interfaces
        self.username = cfg.CONF.arraynetworks.array_api_user
        self.password = cfg.CONF.arraynetworks.array_api_password
        self._load_driver()

    def _load_driver(self):
        self.client = None

        LOG.debug('loading LBaaS driver %s' % cfg.CONF.arraynetworks.array_device_driver)
        try:
            self.client = importutils.import_object(
                cfg.CONF.arraynetworks.array_device_driver,
                self.hosts, self.interfaces, self.username,
                self.password)
            return
        except ImportError as ie:
            msg = ('Error importing loadbalancer device driver: %s error %s'
                   % (cfg.CONF.arraynetworks.array_device_driver, repr(ie)))
            LOG.error(msg)
            raise SystemExit(msg)

    def create_vip(self, context, vip, updated=True):
        LOG.debug("Create a vip on Array ADC device")
        LOG.debug("vip = %s",vip)

        argu = {}
        sp_type = None
        ck_name = None
        vip_port_mac = None

        port_id = vip['port_id']
        vlan_tag = db.get_vlan_id_by_port_cmcc(context, port_id)
        if not vlan_tag:
            LOG.debug("Cann't get the vlan_tag by port_id(%s)", port_id)
        else:
            LOG.debug("Got the vlan_tag(%s) by port_id(%s)", vlan_tag, port_id)
            vip_port = self.plugin._core_plugin._get_port(context, port_id)
            LOG.debug("Got the vip_port(%s)" % vip_port)
            vip_port_mac = vip_port['mac_address']

        if vip['session_persistence']:
            sp_type = vip['session_persistence']['type']
            ck_name = vip['session_persistence'].get('cookie_name', None)

        tenant_id = vip['tenant_id']

        pool = self.plugin.get_pool(context, vip['pool_id'])
        argu['lb_algorithm'] = pool.get('lb_method', None)

        subnet_id = vip['subnet_id']
        subnet = self.plugin._core_plugin.get_subnet(context, subnet_id)
        member_network = netaddr.IPNetwork(subnet['cidr'])
        gateway_ip = subnet['gateway_ip']

        argu['tenant_id'] = tenant_id
        argu['pool_id'] = vip['pool_id']
        argu['vlan_tag'] = str(vlan_tag)
        argu['vip_id'] = vip['id']
        argu['vip_address'] = vip['address']
        argu['vip_port_mac'] = vip_port_mac
        argu['netmask'] = str(member_network.netmask)
        argu['gateway_ip'] = gateway_ip
        argu['protocol'] = vip['protocol']
        argu['protocol_port'] = vip['protocol_port']
        argu['connection_limit'] = vip['connection_limit']
        argu['session_persistence_type'] = sp_type
        argu['cookie_name'] = ck_name

        interface_mapping = {}
        if len(self.hosts) > 1:
            cnt = 0
            LOG.debug("self.hosts(%s): len(%d)", self.hosts, len(self.hosts))
            for host in self.hosts:
                interfaces = {}
                port_data = {
                    'tenant_id': tenant_id,
                    'name': '_lb-port-' + str(cnt) + '-'+ subnet_id,
                    'network_id': subnet['network_id'],
                    'mac_address': attributes.ATTR_NOT_SPECIFIED,
                    'admin_state_up': False,
                    'device_id': '_lb-port-' + str(cnt) + subnet_id,
                    'device_owner': DRIVER_NAME,
                    'fixed_ips': [{'subnet_id': subnet_id}]
                }
                cnt += 1
                LOG.debug("Will create port(%s) for host(%s)", port_data, host)
                port = self.plugin._core_plugin.create_port(context, {'port': port_data})
                interfaces['address'] = port['fixed_ips'][0]['ip_address']
                interfaces['port_id'] = port['id']
                interface_mapping[host] = interfaces
        argu['interface_mapping'] = interface_mapping
        self.client.allocate_vip(argu)

        #Add the member into this group
        for member_id in pool['members']:
            member = self.plugin.get_member(context, member_id)
            LOG.debug("Will create a member(%s) = %s", (member_id, member))
            self.create_member(context, member, updated=False)

        #Add the health monitor into this group
        for hm_id in pool['health_monitors']:
            LOG.debug("Get pool_hm: %s", hm_id)
            hm = self.plugin.get_health_monitor(context, hm_id)
            LOG.debug("A hm(%s) = %s", (hm_id, hm))
            self.create_pool_health_monitor(context, hm, pool['id'], updated=False)

        if updated:
            self.client.write_memory(argu)
            status = constants.ACTIVE
            self.plugin.update_status(context, loadbalancer_db.Vip, vip["id"],
                                      status)


    def update_vip(self, context, old_vip, vip):
        LOG.debug("Update a vip on Array apv device")
        LOG.debug("old vip = %s", old_vip)
        LOG.debug("vip = %s", vip)
        need_recreate = False
        need_rebuild = False

        # need double check
        if old_vip['pool_id'] != vip['pool_id']:
            need_rebuild = True
        for changed in ('connection_limit', 'session_persistence'):
            if old_vip[changed] != vip[changed]:
                need_recreate = True

        if need_rebuild:
            # Operations for old pool
            # 0. get the old pool
            LOG.debug("Will get the old_pool by id: %s", old_vip['pool_id'])
            old_pool = self.plugin.get_pool(context, old_vip['pool_id'])

            # 1. delete the group/member/health_monitor from old pool
            LOG.debug("Will delete the member, health_monitor and pool by old_pool(%s)", old_pool)
            self.delete_pool(context, old_pool, updated=False)

            # 2. delete the vip from old pool
            LOG.debug("Will delete the old_vip: %s", old_vip)
            self.delete_vip(context, old_vip, updated=False)

            # 3. create the vip and pool from old pool
            LOG.debug("Will re-create the old_pool: %s", old_pool)
            self.create_pool(context, old_pool, updated=False)

            # FIXME: In fact, step 4 and 5 can't work. since it doesn't have "slb group"
            # 4. create the member from old pool
            for member_id in old_pool['members']:
                member = self.plugin.get_member(context, member_id)
                LOG.debug("Will create a member(%s) = %s", (member_id, member))
                self.create_member(context, member, updated=False)

            # 5. create the health_monitor from old pool
            for hm_id in old_pool['health_monitors']:
                LOG.debug("Get pool_hm: %s", hm_id)
                hm = self.plugin.get_health_monitor(context, hm_id)
                LOG.debug("A hm(%s) = %s", (hm_id, hm))
                self.create_pool_health_monitor(context, hm, old_pool['id'], updated=False)

            # Operations for new pool
            # 6. get the new pool
            LOG.debug("Will get the old_pool by id: %s", vip['pool_id'])
            pool = self.plugin.get_pool(context, vip['pool_id'])

            # 7. delete the group/member/health_monitor from old pool
            LOG.debug("Will delete the member, health_monitor and pool by old_pool(%s)", old_pool)
            self.delete_pool(context, pool, updated=False)

            # 8. create the group and vip from new pool
            LOG.debug("Will create group and vip: %s", vip)
            self.create_vip(context, vip, updated=False)

            # 9. create the member from new pool
            for member_id in pool['members']:
                member = self.plugin.get_member(context, member_id)
                LOG.debug("Will create a member(%s) = %s", (member_id, member))
                self.create_member(context, member, updated=False)

            # 10. create the health_monitor from new pool
            for hm_id in pool['health_monitors']:
                LOG.debug("Get pool_hm: %s", hm_id)
                hm = self.plugin.get_health_monitor(context, hm_id)
                LOG.debug("A hm(%s) = %s", (hm_id, hm))
                self.create_pool_health_monitor(context, hm, pool['id'], updated=False)

            # 11. write memory to vip
            argu = {}
            argu['tenant_id'] = vip['tenant_id']
            argu['pool_id'] = vip['pool_id']
            self.client.write_memory(argu)

            # 12. write memory to old_vip
            argu = {}
            argu['tenant_id'] = old_vip['tenant_id']
            argu['pool_id'] = old_vip['pool_id']
            self.client.write_memory(argu)
        elif need_recreate:
            # 0. get the old pool
            LOG.debug("Will get the old_pool by id: %s", old_vip['pool_id'])
            old_pool = self.plugin.get_pool(context, old_vip['pool_id'])

            # 1. delete the group/member/health_monitor from old pool
            LOG.debug("Will delete the member, health_monitor and pool by old_pool(%s)", old_pool)
            self.delete_pool(context, old_pool, updated=False)

            # 2. delete the vip from old pool
            LOG.debug("Will delete the old_vip: %s", old_vip)
            self.delete_vip(context, old_vip, updated=False)

            # 3. create the group and vip from new pool
            LOG.debug("Will create group and vip: %s", vip)
            self.create_vip(context, vip, updated=False)

            # 4. get the new pool
            LOG.debug("Will get the old_pool by id: %s", vip['pool_id'])
            pool = self.plugin.get_pool(context, vip['pool_id'])

            # 5. create the member from new pool
            for member_id in pool['members']:
                member = self.plugin.get_member(context, member_id)
                LOG.debug("Will create a member(%s) = %s", (member_id, member))
                self.create_member(context, member, updated=False)

            # 6. create the health_monitor from new pool
            for hm_id in pool['health_monitors']:
                LOG.debug("Get pool_hm: %s", hm_id)
                hm = self.plugin.get_health_monitor(context, hm_id)
                LOG.debug("A hm(%s) = %s", (hm_id, hm))
                self.create_pool_health_monitor(context, hm, pool['id'], updated=False)
            argu = {}
            argu['tenant_id'] = vip['tenant_id']
            argu['pool_id'] = vip['pool_id']
            self.client.write_memory(argu)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Vip, old_vip["id"],
                                  status)

    def delete_vip(self, context, vip, updated=True):
        LOG.debug("Delete a vip on Array apv device")
        LOG.debug("vip = %s", vip)

        argu = {}
        sp_type = None
        port_id = vip['port_id']
        vlan_tag = db.get_vlan_id_by_port_cmcc(context, port_id)
        if not vlan_tag:
            LOG.debug("Cann't get the vlan_tag by port_id(%s)", port_id)

        if vip['session_persistence']:
            sp_type = vip['session_persistence']['type']

        pool = self.plugin.get_pool(context, vip['pool_id'])

        argu['tenant_id'] = vip['tenant_id']
        argu['lb_algorithm'] = pool.get('lb_method', None)
        argu['vlan_tag'] = str(vlan_tag)
        argu['vip_id'] = vip['id']
        argu['pool_id'] = vip['pool_id']
        argu['vip_address'] = vip['address']
        argu['protocol'] = vip['protocol']
        argu['session_persistence_type'] = sp_type

        if len(self.hosts) > 1:
            LOG.debug("Will delete the port created by ourselves.")
            mapping = self.client.get_cached_map(argu)
            if mapping:
                for host in self.hosts:
                    port_id = mapping[host]
                    self.plugin._core_plugin.delete_port(context, port_id)

        self.client.deallocate_vip(argu, updated)
        if updated:
            self.client.write_memory(argu)
            self.plugin._delete_db_vip(context, vip['id'])


    def create_pool(self, context, pool, updated=True):
        LOG.debug("Create a pool on Array apv device")
        LOG.debug("create pool = %s",pool)

        argu = {}
        argu['tenant_id'] = pool['tenant_id']
        argu['pool_id'] = pool["id"]
        argu["lb_algorithm"] = pool["lb_method"]
        self.client.create_group(argu)

        if updated:
            self.client.write_memory(argu)
            status = constants.ACTIVE
            self.plugin.update_status(context, loadbalancer_db.Pool,
                                      pool["id"], status)


    def update_pool(self, context, old_pool, pool):
        LOG.debug("Update a pool on Array apv device")
        LOG.debug("Update old pool = %s", old_pool)
        LOG.debug("Update pool = %s", pool)
        need_recreate = False


        if old_pool['lb_method'] != pool['lb_method']:
            need_recreate = True

        if need_recreate:
            members = []
            pool_hms = []
            vip = None
            if pool['vip_id']:
                vip = self.plugin.get_vip(context, pool['vip_id'])
                LOG.debug("VIP(%s): %s", (pool['vip_id'], vip))
                self.delete_vip(context, vip, updated=False)

            self.delete_pool(context, pool, updated=False)

            LOG.debug("Have clean all the configuration, and then will re-configure them")
            time.sleep(1)

            self.create_pool(context, pool, updated=False)

            if pool['vip_id']:
                LOG.debug("Will re-create VIP(%s): %s", (pool['vip_id'], vip))
                self.create_vip(context, vip, updated=False)

            for member in members:
                LOG.debug("Will re-create the member: %s", member)
                self.create_member(context, member, updated=False)

            for hm in pool_hms:
                LOG.debug("Will re-create the hm: %s", hm)
                self.create_pool_health_monitor(context, hm, pool['id'], updated=False)

            argu = {}
            argu['tenant_id'] = pool['tenant_id']
            argu['pool_id'] = pool["id"]
            self.client.write_memory(argu)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Pool,
                                  old_pool["id"], status)

    def delete_pool(self, context, pool, updated=True):
        LOG.debug("Delete a pool on Array apv device")
        LOG.debug("Delete pool = %s", pool)

        argu = {}
        members_dict = {}
        argu['tenant_id'] = pool['tenant_id']
        argu['pool_id'] = pool["id"]
        argu["lb_algorithm"] = pool["lb_method"]
        argu['health_monitors'] = pool['health_monitors']

        for member_id in pool['members']:
            members_dict[member_id] = pool.get('protocol', None)
        argu['members'] = members_dict
        self.client.delete_group(argu, updated)

        if updated:
            self.plugin._delete_db_pool(context, pool['id'])

    def create_member(self, context, member, updated=True):
        LOG.debug("Create a member on Array apv device")
        LOG.debug("member=%s",member)
        status = constants.ACTIVE

        pool = self.plugin.get_pool(context, member['pool_id'])

        argu = {}
        argu['tenant_id'] = member['tenant_id']
        argu['protocol'] = pool.get('protocol', None)
        argu['pool_id'] = member['pool_id']
        argu['member_id'] = member['id']
        argu['member_address'] = member['address']
        argu['member_port'] = member['protocol_port']
        argu['member_weight'] = member['weight']

        self.client.create_member(argu)

        if updated:
            self.client.write_memory(argu)
            self.plugin.update_status(context, loadbalancer_db.Member,
                                      member["id"], status)

    def update_member(self,context,old_member,member):
        LOG.debug("Update a member on Array apv device")
        LOG.debug("old_member=%s",old_member)
        LOG.debug("member=%s",member)
        need_update = False
        need_recreate = False

        if old_member['pool_id'] != member['pool_id']:
            need_recreate = True
        elif old_member['weight'] != member['weight']:
            need_update = True

        if need_update:
            argu = {}
            argu['pool_id'] = member['pool_id']
            argu['member_id'] = member['id']
            argu['member_weight'] = member['weight']
            self.client.update_member(argu)
            self.client.write_memory(argu)
        elif need_recreate:
            self.delete_member(context, old_member, updated=False)
            self.create_member(context, member, updated=False)
            argu = {}
            argu['pool_id'] = member['pool_id']
            argu['tenant_id'] = member['tenant_id']
            self.client.write_memory(argu)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Member,
                                  old_member["id"], status)


    def delete_member(self, context, member, updated=True):
        LOG.debug("Delete a member on Array apv device")
        LOG.debug("member=%s",member)

        argu = {}
        pool = self.plugin.get_pool(context, member['pool_id'])

        argu['tenant_id'] = member['tenant_id']
        argu['protocol'] = pool.get('protocol', None)
        argu['member_id'] = member['id']
        argu['pool_id'] = member['pool_id']

        self.client.delete_member(argu)

        if updated:
            self.client.write_memory(argu)
            self.plugin._delete_db_member(context, member['id'])


    def create_pool_health_monitor(self, context, health_monitor, pool_id, updated=True):
        LOG.debug("Create a pool health monitor on Array apv device")
        LOG.debug("health_monito=%s",health_monitor)
        LOG.debug("pool_id=%s",pool_id)

        lm_type = health_monitor['type']
        lm_url = None
        lm_http_method = None
        lm_expected_codes = None
        if lm_type == 'HTTP' or lm_type == 'HTTPS':
            lm_url = health_monitor['url_path']
            lm_http_method = health_monitor['http_method']
            lm_expected_codes = health_monitor['expected_codes']

        argu = {}
        argu['tenant_id'] = health_monitor['tenant_id']
        argu['pool_id'] = pool_id
        argu['hm_id'] = health_monitor['id']
        argu['hm_type'] = lm_type
        argu['hm_delay'] = health_monitor['delay']
        argu['hm_max_retries'] = health_monitor['max_retries']
        argu['hm_timeout'] = health_monitor['timeout']
        argu['hm_http_method'] = lm_http_method
        argu['hm_url'] = lm_url
        argu['hm_expected_codes'] = lm_expected_codes

        status = constants.ACTIVE
        self.client.create_health_monitor(argu)

        if updated:
            self.client.write_memory(argu)
            self.plugin.update_pool_health_monitor(context,
                                                   health_monitor['id'],
                                                   pool_id,
                                                   status, "")

    def update_pool_health_monitor(self,context,old_health_monitor,health_monitor,pool_id):
        LOG.debug("Update a pool health monitor on Array apv device")
        LOG.debug("old_health_monitor=%s",old_health_monitor)
        LOG.debug("health_monitor=%s",health_monitor)

        self.delete_pool_health_monitor(
                                       context,
                                       old_health_monitor,
                                       pool_id,
                                       updated=False
                                       )

        self.create_pool_health_monitor(
                                       context,
                                       health_monitor,
                                       pool_id,
                                       updated=False
                                       )

        argu = {}
        argu['tenant_id'] = health_monitor['tenant_id']
        argu['pool_id'] = pool_id
        self.client.write_memory(argu)

        status = constants.ACTIVE
        self.plugin.update_pool_health_monitor(context,
                                               health_monitor['id'],
                                               pool_id,
                                               status, "")


    def delete_pool_health_monitor(self, context, health_monitor, pool_id, updated=True):
        LOG.debug("Delete a pool health monitor on Array apv device")
        LOG.debug("health_monito=%s",health_monitor)
        LOG.debug("pool_id=%s",pool_id)

        argu = {}
        argu['tenant_id'] = health_monitor['tenant_id']
        argu['pool_id'] = pool_id
        argu['hm_id'] = health_monitor['id']

        self.client.delete_health_monitor(argu)
        if updated:
            self.client.write_memory(argu)
            self.plugin._delete_db_pool_health_monitor(context,
                                                           health_monitor['id'],
                                                           pool_id)

    def stats(self,context,pool_id):
        LOG.debug("Retrieve pool statistics from the Array apv device")
