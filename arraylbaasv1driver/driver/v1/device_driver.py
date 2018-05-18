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

from oslo.config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from neutron.api.v2 import attributes
from neutron.plugins.common import constants

from neutron_lbaas.db.loadbalancer import loadbalancer_db
from neutron_lbaas.services.loadbalancer.drivers import abstract_driver

from arraylbaasv1driver.driver.v1 import db
#from arraylbaasv1driver.driver.v1 import apv_driver

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
        default=('arraylbaasv1driver.driver.v1.apv_driver.'
                 'ArrayAPVAPIDriver'),
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

    def create_vip(self, context, vip):
        LOG.debug("Create a vip on Array ADC device")
        LOG.debug("vip = %s",vip)

        argu = {}
        sp_type = None
        ck_name = None

        port_id = vip['port_id']
        vlan_tag = db.get_vlan_id_by_port_cmcc(context, port_id)
        if not vlan_tag:
            LOG.debug("Cann't get the vlan_tag by port_id(%s)", port_id)
        else:
            LOG.debug("Got the vlan_tag(%s) by port_id(%s)", vlan_tag, port_id)
        if vip['session_persistence']:
            sp_type = vip['session_persistence']['type']
            ck_name = vip['session_persistence']['cookie_name']

        tenant_id = vip['tenant_id']

        pool = self.plugin.get_pool(context, vip['pool_id'])
        argu['lb_algorithm'] = pool.get('lb_method', None)

        subnet_id = vip['subnet_id']
        subnet = self.plugin._core_plugin.get_subnet(context, subnet_id)
        member_network = netaddr.IPNetwork(subnet['cidr'])

        argu['tenant_id'] = tenant_id
        argu['pool_id'] = vip['pool_id']
        argu['vlan_tag'] = vlan_tag
        argu['vip_id'] = vip['id']
        argu['vip_address'] = vip['address']
        argu['netmask'] = str(member_network.netmask)
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

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Vip, vip["id"],
                                  status)


    def update_vip(self, context, old_vip, vip):
        LOG.debug("Update a vip on Array apv device")
        LOG.debug("old vip = %s", old_vip)
        LOG.debug("vip = %s", vip)
        # FIXME
        self.delete_vip(context, old_vip)
        self.create_vip(context, vip)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Vip, old_vip["id"],
                                  status)

    def delete_vip(self, context, vip):
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
        argu['vlan_tag'] = vlan_tag
        argu['vip_id'] = vip['id']
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

        self.client.deallocate_vip(argu)
        self.plugin._delete_db_vip(context, vip['id'])


    def create_pool(self,context,pool):
        LOG.debug("Create a pool on Array apv device")
        LOG.debug("create pool = %s",pool)

        argu = {}
        argu['tenant_id'] = pool['tenant_id']
        argu['pool_id'] = pool["id"]
        argu["lb_algorithm"] = pool["lb_method"]
        self.client.create_group(argu)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Pool,
                                  pool["id"], status)


    def update_pool(self, context, old_pool, pool):
        LOG.debug("Update old pool = %s", old_pool)
        LOG.debug("Delete pool = %s", pool)

        self.delete_pool(context, old_pool)
        self.create_pool(context, old_pool)

        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Pool,
                                  old_pool["id"], status)

    def delete_pool(self, context, pool):
        LOG.debug("Delete a pool on Array apv device")
        LOG.debug("Delete pool = %s", pool)

        argu = {}
        argu['tenant_id'] = pool['tenant_id']
        argu['pool_id'] = pool["id"]
        argu["lb_algorithm"] = pool["lb_method"]
        self.client.delete_group(argu)

        self.plugin._delete_db_pool(context, pool['id'])

    def create_member(self, context, member):
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

        self.plugin.update_status(context, loadbalancer_db.Member,
                                  member["id"], status)

    def update_member(self,context,old_member,member):
        LOG.debug("Update a member on Array apv device")
        LOG.debug("old_member=%s",old_member)
        LOG.debug("member=%s",member)
        #FIXME
        self.client.delete_member(context, old_member)
        self.client.create_member(context, member)
        status = constants.ACTIVE
        self.plugin.update_status(context, loadbalancer_db.Member,
                                  old_member["id"], status)


    def delete_member(self,context,member):
        LOG.debug("Delete a member on Array apv device")
        LOG.debug("member=%s",member)

        argu = {}
        pool = self.plugin.get_pool(context, member['pool_id'])

        argu['tenant_id'] = member['tenant_id']
        argu['protocol'] = pool.get('protocol', None)
        argu['member_id'] = member['id']

        self.client.delete_member(argu)
        self.plugin._delete_db_member(context, member['id'])


    def create_pool_health_monitor(self, context, health_monitor, pool_id):
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

        self.plugin.update_pool_health_monitor(context,
                                               health_monitor['id'],
                                               pool_id,
                                               status, "")

    def update_pool_health_monitor(self,context,old_health_monitor,health_monitor,pool_id):
        LOG.debug("Update a pool health monitor on Array apv device")
        LOG.debug("old_health_monitor=%s",old_health_monitor)
        LOG.debug("health_monitor=%s",health_monitor)
        # FIXME
        self.delete_pool_health_monitor(
                                       context,
                                       old_health_monitor,
                                       pool_id
                                       )

        self.create_pool_health_monitor(
                                       context,
                                       health_monitor,
                                       pool_id
                                       )
        status = constants.ACTIVE
        self.plugin.update_pool_health_monitor(context,
                                               health_monitor['id'],
                                               pool_id,
                                               status, "")


    def delete_pool_health_monitor(self, context, health_monitor, pool_id):
        LOG.debug("Delete a pool health monitor on Array apv device")
        LOG.debug("health_monito=%s",health_monitor)
        LOG.debug("pool_id=%s",pool_id)

        argu = {}
        argu['tenant_id'] = health_monitor['tenant_id']
        argu['pool_id'] = pool_id
        argu['hm_id'] = health_monitor['id']

        self.client.delete_health_monitor(argu)
        self.plugin._delete_db_pool_health_monitor(context,
                                                       health_monitor['id'],
                                                       pool_id)

    def stats(self,context,pool_id):
        LOG.debug("Retrieve pool statistics from the Array apv device")
