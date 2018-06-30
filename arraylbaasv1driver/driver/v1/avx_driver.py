# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
import requests
import logging
import time

from arraylbaasv1driver.driver.v1.exceptions import ArrayADCException
from arraylbaasv1driver.driver.v1.adc_cache import LogicalAVXCache
from arraylbaasv1driver.driver.v1.adc_device import ADCDevice

LOG = logging.getLogger(__name__)


class ArrayAVXAPIDriver(object):
    """ The real implementation on host to push config to
        APV instance via RESTful API
    """
    def __init__(self, management_ip, in_interface, user_name, user_passwd):
        self.user_name = user_name
        self.user_passwd = user_passwd
        self.in_interface = "port2"
        self.hostnames = management_ip
        self.base_rest_urls = ["https://" + host + ":9997/rest/avx" for host in self.hostnames]
        self.cache = LogicalAVXCache(in_interface)


    def get_auth(self):
        return (self.user_name, self.user_passwd)

    def get_va_name(self, argu):
        if not argu:
            msg = "No argument, raise it"
            raise ArrayADCException(msg)

        pool_id = argu.get('pool_id', None)
        if not pool_id:
            msg = "No pool_id in argument, raise it"
            raise ArrayADCException(msg)

        va_name = self.cache.find_va_by_pool(pool_id)
        if not va_name:
            LOG.debug("Failed to find any VA, continue...")
            va_name = self.cache.get_va_by_pool(pool_id)
        if not va_name:
            msg = "Cannot get the vAPV by pool_id(%s)" % pool_id
            raise ArrayADCException(msg)
        return va_name

    def allocate_vip(self, argu):
        """ allocation vip when create_vip"""

        va_name = self.get_va_name(argu)

        # create vip
        self._create_vip(
                         va_name,
                         argu['tenant_id'],
                         argu['vip_id'],
                         argu['vlan_tag'],
                         argu['vip_address'],
                         argu['netmask'],
                         argu['interface_mapping'],
                         argu['vip_port_mac'],
                         argu['gateway_ip']
                        )

        # create group
        self._create_group(
                          va_name,
                          argu['pool_id'],
                          argu['lb_algorithm'],
                          argu['session_persistence_type']
                          )

        # create vs
        self._create_vs(
                        va_name,
                        argu['vip_id'],
                        argu['vip_address'],
                        argu['protocol'],
                        argu['protocol_port'],
                        argu['connection_limit']
                       )

        # create policy
        self._create_policy(
                            va_name,
                            argu['pool_id'],
                            argu['vip_id'],
                            argu['session_persistence_type'],
                            argu['lb_algorithm'],
                            argu['cookie_name']
                           )

        # config the HA
        self.config_ha(
                       va_name,
                       argu['vlan_tag'],
                       argu['vip_address']
                      )

    def deallocate_vip(self, argu, updated=True):
        """ Delete VIP in lb_delete_vip """

        va_name = self.get_va_name(argu)

        # delete group
        self._delete_group(
                           va_name,
                           argu['pool_id'],
                           )

        # delete policy
        self._delete_policy(
                           va_name,
                           argu['vip_id'],
                           argu['session_persistence_type'],
                           argu['lb_algorithm']
                           )

        # delete vs
        self._delete_vs(
                        va_name,
                        argu['vip_id'],
                        argu['protocol']
                       )

        # delete vip
        self._delete_vip(
                         va_name,
                         argu['tenant_id'],
                         argu['vip_id'],
                         argu['vlan_tag'],
                         updated
                        )

        self.no_ha(va_name, argu['vlan_tag'])


    def _create_vip(self,
                    va_name,
                    pool_id,
                    vip_id,
                    vlan_tag,
                    vip_address,
                    netmask,
                    interface_mapping,
                    vip_port_mac,
                    gateway_ip
                   ):
        """ create vip"""

        interface_name = self.in_interface

        # mock to set the mac
        if vip_port_mac:
            mock_mac = "0c:c4:7a:7c:af:f6"
            cmd_apv_config_mac = "interface mac %s %s" % (interface_name, mock_mac)
            cmd_avx_config_mac = "va run %s \"%s\"" % (va_name, cmd_apv_config_mac)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_config_mac)

        time.sleep(1)

        # update the mac
        if vip_port_mac:
            cmd_apv_config_mac = "interface mac %s %s" % (interface_name, vip_port_mac)
            cmd_avx_config_mac = "va run %s \"%s\"" % (va_name, cmd_apv_config_mac)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_config_mac)

        # create vlan
        if vlan_tag != 'None':
            interface_name = "vlan." + vlan_tag
            cmd_apv_config_vlan = ADCDevice.vlan_device(
                                                        self.in_interface,
                                                        interface_name,
                                                        vlan_tag
                                                       )
            cmd_avx_config_vlan = "va run %s \"%s\"" % (va_name, cmd_apv_config_vlan)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_config_vlan)

        # configure vip
        if len(self.hostnames) == 1:
            LOG.debug("Configure the vip address into interface")
            cmd_apv_config_ip = ADCDevice.configure_ip(interface_name, vip_address, netmask)
            cmd_apv_config_route = ADCDevice.configure_route(gateway_ip)

            cmd_avx_config_ip = "va run %s \"%s\"" % (va_name, cmd_apv_config_ip)
            cmd_avx_config_route = "va run %s \"%s\"" % (va_name, cmd_apv_config_route)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_config_ip)
                self.run_cli_extend(base_rest_url, cmd_avx_config_route)
        else:
            for host in self.hostnames:
                iface = interface_mapping[host]
                ip = iface['address']

                cmd_apv_config_ip = ADCDevice.configure_ip(interface_name, ip, netmask)
                cmd_apv_config_route = ADCDevice.configure_route(gateway_ip)

                cmd_avx_config_ip = "va run %s \"%s\"" % (va_name, cmd_apv_config_ip)
                cmd_avx_config_route = "va run %s \"%s\"" % (va_name, cmd_apv_config_route)
                base_rest_url = "https://" + host + ":9997/rest/avx"
                self.run_cli_extend(base_rest_url, cmd_avx_config_ip)
                self.run_cli_extend(base_rest_url, cmd_avx_config_route)
                self.cache.put(pool_id, vip_id, host, iface['port_id'])
            self.cache.dump()


    def _delete_vip(self,
                    va_name,
                    pool_id,
                    vip_id,
                    vlan_tag,
                    updated
                   ):

        interface_name = self.in_interface
        if vlan_tag != 'None':
            interface_name = "vlan." + vlan_tag

        # configure vip
        cmd_apv_no_ip = ADCDevice.no_ip(interface_name)
        cmd_apv_no_route = ADCDevice.clear_route()

        cmd_avx_no_ip = "va run %s \"%s\"" % (va_name, cmd_apv_no_ip)
        cmd_avx_no_route = "va run %s \"%s\"" % (va_name, cmd_apv_no_route)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_no_ip)
            self.run_cli_extend(base_rest_url, cmd_avx_no_route)

        if updated:
            self.cache.remove_vip(pool_id, vip_id)
            self.cache.dump()

        if vlan_tag != 'None':
            cmd_apv_no_vlan_device = ADCDevice.no_vlan_device(interface_name)
            cmd_avx_no_vlan_device = "va run %s \"%s\"" % (va_name, cmd_apv_no_vlan_device)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_no_vlan_device)


    def _create_vs(self,
                   va_name,
                   vip_id,
                   vip_address,
                   protocol,
                   protocol_port,
                   connection_limit):

        cmd_apv_create_vs = ADCDevice.create_virtual_service(
                                                             vip_id,
                                                             vip_address,
                                                             protocol_port,
                                                             protocol,
                                                             connection_limit
                                                            )
        cmd_avx_create_vs = "va run %s \"%s\"" % (va_name, cmd_apv_create_vs)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_create_vs)


    def _delete_vs(self, va_name, vip_id, protocol):
        cmd_apv_no_vs = ADCDevice.no_virtual_service(
                                                     vip_id,
                                                     protocol
                                                    )
        cmd_avx_no_vs = "va run %s \"%s\"" % (va_name, cmd_apv_no_vs)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_no_vs)


    def _create_policy(self,
                       va_name,
                       pool_id,
                       vip_id,
                       session_persistence_type,
                       lb_algorithm,
                       cookie_name):
        """ Create SLB policy """

        cmd_apv_create_policy = ADCDevice.create_policy(
                                                        vip_id,
                                                        pool_id,
                                                        lb_algorithm,
                                                        session_persistence_type,
                                                        cookie_name
                                                       )

        cmd_avx_create_policy = "va run %s \"%s\"" % (va_name, cmd_apv_create_policy)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_create_policy)


    def _delete_policy(self,
                       va_name,
                       vip_id,
                       session_persistence_type,
                       lb_algorithm
                      ):
        """ Delete SLB policy """
        cmd_apv_no_policy = ADCDevice.no_policy(
                                                vip_id,
                                                lb_algorithm,
                                                session_persistence_type
                                               )
        cmd_avx_no_policy = "va run %s \"%s\"" % (va_name, cmd_apv_no_policy)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_no_policy)



    def create_group(self, argu):
        """ Create SLB group in lb-pool-create"""

        va_name = self.get_va_name(argu)



    def _create_group(self, va_name, pool_id, lb_algorithm, sp_type):

        cmd_apv_create_group = ADCDevice.create_group(pool_id, lb_algorithm, sp_type)
        cmd_avx_create_group = "va run %s \"%s\"" % (va_name, cmd_apv_create_group)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_create_group)


    def _delete_group(self, va_name, pool_id):

        cmd_apv_delete_group = ADCDevice.no_group(pool_id)
        cmd_avx_delete_group = "va run %s \"%s\"" % (va_name, cmd_apv_delete_group)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_delete_group)


    def delete_group(self, argu, updated = True):
        """Delete SLB group in lb-pool-delete"""

        va_name = self.get_va_name(argu)

        cmd_apv_no_group = ADCDevice.no_group(argu['pool_id'])
        cmd_avx_no_group = "va run %s \"%s\"" % (va_name, cmd_apv_no_group)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_no_group)

        member_dict = argu['members']
        for member in member_dict.keys():
            cmd_apv_no_member = ADCDevice.no_real_server(member_dict[member], member)
            cmd_avx_no_member = "va run %s \"%s\"" % (va_name, cmd_apv_no_member)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_no_member)

        for health_monitor in argu['health_monitors']:
            cmd_apv_no_hm = ADCDevice.no_health_monitor(health_monitor)
            cmd_avx_no_hm = "va run %s \"%s\"" % (va_name, cmd_apv_no_hm)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_avx_no_hm)

        if updated:
            self.write_memory(argu)
            self.cache.remove_group(argu['pool_id'])


    def create_member(self, argu):
        """ create a member"""

        va_name = self.get_va_name(argu)

        cmd_apv_create_real_server = ADCDevice.create_real_server(
                                                       argu['member_id'],
                                                       argu['member_address'],
                                                       argu['member_port'],
                                                       argu['protocol']
                                                       )

        cmd_apv_add_rs_into_group = ADCDevice.add_rs_into_group(
                                                               argu['pool_id'],
                                                               argu['member_id'],
                                                               argu['member_weight']
                                                               )

        cmd_avx_create_rs = "va run %s \"%s\"" % (va_name, cmd_apv_create_real_server)
        cmd_avx_add_rs_into_group = "va run %s \"%s\"" % (va_name, cmd_apv_add_rs_into_group)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_create_rs)
            self.run_cli_extend(base_rest_url, cmd_avx_add_rs_into_group)

    def update_member(self, argu):
        """ Update a member"""

        va_name = self.get_va_name(argu)
        cmd_apv_add_rs_into_group = ADCDevice.add_rs_into_group(
                                                               argu['pool_id'],
                                                               argu['member_id'],
                                                               argu['member_weight']
                                                               )

        cmd_avx_add_rs_into_group = "va run %s \"%s\"" % (va_name, cmd_apv_add_rs_into_group)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_add_rs_into_group)


    def delete_member(self, argu):
        """ Delete a member"""

        va_name = self.get_va_name(argu)

        cmd_apv_no_rs = ADCDevice.no_real_server(argu['protocol'], argu['member_id'])
        cmd_avx_no_rs = "va run %s \"%s\"" % (va_name, cmd_apv_no_rs)

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_no_rs)


    def create_health_monitor(self, argu):

        va_name = self.get_va_name(argu)

        cmd_apv_create_hm = ADCDevice.create_health_monitor(
                                                           argu['hm_id'],
                                                           argu['hm_type'],
                                                           argu['hm_delay'],
                                                           argu['hm_max_retries'],
                                                           argu['hm_timeout'],
                                                           argu['hm_http_method'],
                                                           argu['hm_url'],
                                                           argu['hm_expected_codes']
                                                           )

        cmd_apv_attach_hm = ADCDevice.attach_hm_to_group(argu['pool_id'], argu['hm_id'])

        cmd_avx_create_hm = "va run %s \"%s\"" % (va_name, cmd_apv_create_hm)
        cmd_avx_attach_hm = "va run %s \"%s\"" % (va_name, cmd_apv_attach_hm)

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_create_hm)
            self.run_cli_extend(base_rest_url, cmd_avx_attach_hm)

    def delete_health_monitor(self, argu):

        va_name = self.get_va_name(argu)

        cmd_apv_detach_hm = ADCDevice.detach_hm_to_group(argu['pool_id'], argu['hm_id'])

        cmd_apv_no_hm = ADCDevice.no_health_monitor(argu['hm_id'])

        cmd_avx_detach_hm = "va run %s \"%s\"" % (va_name, cmd_apv_detach_hm)
        cmd_avx_no_hm = "va run %s \"%s\"" % (va_name, cmd_apv_no_hm)

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_detach_hm)
            self.run_cli_extend(base_rest_url, cmd_avx_no_hm)


    def write_memory(self, argu):
        va_name = self.get_va_name(argu)

        cmd_apv_write_memory = ADCDevice.write_memory()
        cmd_avx_write_memory = "va run %s \"%s\"" % (va_name, cmd_apv_write_memory)

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_write_memory)


    def run_cli_extend(self, base_rest_url, cmd):
        url = base_rest_url + '/cli_extend'
        payload = {
            "cmd": cmd
        }
        LOG.debug("Run cmd: %s" % cmd)
        r = requests.post(url, json.dumps(payload), auth=self.get_auth(), verify=False)
        if r.status_code != 200:
            msg = r.text
            raise ArrayADCException(msg, r.status_code)

    def no_ha(self, va_name, vlan_tag):
        """ clear the HA configuration when delete_vip """

        if len(self.hostnames) == 1:
            LOG.debug("Only one machine, doesn't need to configure HA")
            return True

        interface_name = self.in_interface
        if vlan_tag != 'None':
            interface_name = "vlan." + vlan_tag

        cmd_apv_disable_cluster = ADCDevice.cluster_disable(interface_name)
        cmd_avx_disable_cluster = "va run %s \"%s\"" % (va_name, cmd_apv_disable_cluster)

        cmd_apv_clear_cluster_config = ADCDevice.cluster_clear_virtual_interface(interface_name)
        cmd_avx_clear_cluster_config = "va run %s \"%s\"" % (va_name, cmd_apv_clear_cluster_config)
        for base_rest_url in self.base_rest_urls:
            # disable the virtual cluster
            self.run_cli_extend(base_rest_url, cmd_avx_disable_cluster)

            # clear the configuration of this virtual ifname
            self.run_cli_extend(base_rest_url, cmd_avx_clear_cluster_config)


    def config_ha(self, va_name, vlan_tag, vip_address):
        """ set the HA configuration when create_vip """

        if len(self.hostnames) == 1:
            LOG.debug("Only one machine, doesn't need to configure HA")
            return True

        interface_name = self.in_interface
        if vlan_tag != 'None':
            interface_name = "vlan." + vlan_tag

        cmd_apv_config_virtual_iface = ADCDevice.cluster_config_virtual_interface(interface_name)
        cmd_apv_config_virtual_vip = ADCDevice.cluster_config_vip(interface_name)
        cmd_apv_cluster_enable = ADCDevice.cluster_enable(interface_name)

        cmd_avx_config_virtual_iface = "va run %s \"%s\"" % (va_name, cmd_apv_config_virtual_iface)
        cmd_avx_config_virtual_vip = "va run %s \"%s\"" % (va_name, cmd_apv_config_virtual_vip)
        cmd_avx_cluster_enable = "va run %s \"%s\"" % (va_name, cmd_apv_cluster_enable)

        priority = 1
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_avx_config_virtual_iface)
            self.run_cli_extend(base_rest_url, cmd_avx_config_virtual_vip)

            priority += 10
            cmd_apv_config_virtual_prior = ADCDevice.cluster_config_priority(interface_name, priority)
            cmd_avx_config_cluster_prior = "va run %s \"%s\"" % (va_name, cmd_apv_config_virtual_prior)
            self.run_cli_extend(base_rest_url, cmd_avx_config_cluster_prior)

            self.run_cli_extend(base_rest_url, cmd_avx_cluster_enable)


    def get_cached_map(self, argu):
        return self.cache.get_interface_map_by_vip(argu['pool_id'], argu['vip_id'])
