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

from arraylbaasv1driver.driver.v1.exceptions import ArrayADCException
from arraylbaasv1driver.driver.v1.adc_cache import LogicalAPVCache
from arraylbaasv1driver.driver.v1.adc_device import ADCDevice

LOG = logging.getLogger(__name__)


class ArrayAPVAPIDriver(object):
    """ The real implementation on host to push config to
        APV instance via RESTful API
    """
    def __init__(self, management_ip, in_interface, user_name, user_passwd):
        self.user_name = user_name
        self.user_passwd = user_passwd
        self.in_interface = in_interface
        self.hostnames = management_ip
        self.base_rest_urls = ["https://" + host + ":9997/rest/apv" for host in self.hostnames]
        self.cache = LogicalAPVCache()


    def get_auth(self):
        return (self.user_name, self.user_passwd)


    def allocate_vip(self, argu):
        """ allocation vip when create_vip"""

        if not argu:
            LOG.error("In allocate_vip, it should not pass the None.")

        if argu['vlan_tag'] == "None":
            argu['vlan_tag'] = None

        # create vip
        self._create_vip(argu['vip_id'],
                         argu['vlan_tag'],
                         argu['vip_address'],
                         argu['netmask'],
                         argu['interface_mapping'],
                         argu['vip_port_mac']
                        )

        # create vs
        self._create_vs(argu['vip_id'],
                        argu['vip_address'],
                        argu['protocol'],
                        argu['protocol_port'],
                        argu['connection_limit']
                       )

        # create policy
        self._create_policy(argu['pool_id'],
                            argu['vip_id'],
                            argu['session_persistence_type'],
                            argu['lb_algorithm'],
                            argu['cookie_name']
                           )

        # config the HA
        self.config_ha(argu['vlan_tag'], argu['vip_address'])

    def deallocate_vip(self, argu):
        """ Delete VIP in lb_delete_vip """

        if not argu:
            LOG.error("In deallocate_vip, it should not pass the None.")

        if argu['vlan_tag'] == "None":
            argu['vlan_tag'] = None

        # delete policy
        self._delete_policy(
                           argu['vip_id'],
                           argu['session_persistence_type'],
                           argu['lb_algorithm']
                           )

        # delete vs
        self._delete_vs(
                       argu['vip_id'],
                       argu['protocol']
                       )

        # delete vip
        self._delete_vip(argu['vip_id'], argu['vlan_tag'])

        self.no_ha(argu['vlan_tag'])


    def _create_vip(self,
                    vip_id,
                    vlan_tag,
                    vip_address,
                    netmask,
                    interface_mapping,
                    vip_port_mac
                   ):
        """ create vip"""

        interface_name = self.in_interface

        # update the mac
        if vip_port_mac:
            cmd_config_mac = "interface mac %s %s" % (interface_name, vip_port_mac)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_config_mac)

        # create vlan
        if vlan_tag:
            interface_name = "vlan." + vlan_tag
            payload = {
                "name": interface_name,
                "tag": vlan_tag,
                "interface": self.in_interface
            }
            for base_rest_url in self.base_rest_urls:
                url = base_rest_url + '/network/interface/VlanInterface'
                LOG.debug("create_vip URL: --%s--", url)
                LOG.debug("create_vip payload: --%s--", url)
                r = requests.post(url, data=json.dumps(payload), auth=self.get_auth(), verify=False)
                if r.status_code != 200:
                    msg = r.text
                    raise ArrayADCException(msg, r.status_code)

        # configure vip
        if len(self.hostnames) == 1:
            LOG.debug("Configure the vip address into interface")
            cmd_config_vip = "ip address %s %s %s" % (interface_name, vip_address, netmask)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_config_vip)
        else:
            for host in self.hostnames:
                iface = interface_mapping[host]
                ip = iface['address']
                cmd_config_vip = "ip address %s %s %s" % (interface_name, ip, netmask)
                base_rest_url = "https://" + host + ":9997/rest/apv"
                self.run_cli_extend(base_rest_url, cmd_config_vip)
                self.cache.put(vip_id, host, iface['port_id'])
            self.cache.dump()


    def _delete_vip(self, vip_id, vlan_tag):
        interface_name = self.in_interface
        if vlan_tag:
            interface_name = "vlan." + vlan_tag

        # configure vip
        LOG.debug("no the vip address into interface")
        cmd_no_ip = "no ip address %s " % (interface_name)
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_no_ip)

        if len(self.hostnames) > 1:
            self.cache.remove(vip_id)
            self.cache.dump()

        if vlan_tag:
            for base_rest_url in self.base_rest_urls:
                url = '%s/network/interface/VlanInterface/%s' % (
                    base_rest_url, interface_name)
                LOG.debug("delete_vip URL: --%s--", url)
                r = requests.delete(url, auth=self.get_auth(), verify=False)
                if r.status_code != 200:
                    msg = r.text
                    raise ArrayADCException(msg, r.status_code)


    def _create_vs(self,
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
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_create_vs)


    def _delete_vs(self, vip_id, protocol):
        cmd_apv_no_vs = ADCDevice.no_virtual_service(
                                                     vip_id,
                                                     protocol
                                                    )
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_no_vs)


    def _create_policy(self,
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

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_create_policy)


    def _delete_policy(self, vip_id, session_persistence_type, lb_algorithm):
        """ Delete SLB policy """

        cmd_apv_no_policy = ADCDevice.no_policy(
                                                vip_id,
                                                lb_algorithm,
                                                session_persistence_type
                                               )
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_no_policy)


    def create_group(self, argu):
        """ Create SLB group in lb-pool-create"""

        if not argu:
            LOG.error("In create_group, it should not pass the None.")

        cmd_apv_create_group = ADCDevice.create_group(argu['pool_id'], argu['lb_algorithm'])
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_create_group)


    def update_group(self, argu):
        """ Create SLB group in lb-pool-create"""

        self.create_group(argu)

    def delete_group(self, argu):
        """Delete SLB group in lb-pool-delete"""

        cmd_apv_no_group = ADCDevice.no_group(argu['pool_id'])
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_no_group)

        member_dict = argu['members']
        for member in member_dict.keys():
            cmd_apv_no_member = ADCDevice.no_real_server(member_dict[member], member)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_apv_no_member)

        for health_monitor in argu['health_monitors']:
            cmd_apv_no_hm = ADCDevice.no_health_monitor(health_monitor)
            for base_rest_url in self.base_rest_urls:
                self.run_cli_extend(base_rest_url, cmd_apv_no_hm)


    def create_member(self, argu):
        """ create a member"""

        if not argu:
            LOG.error("In create_member, it should not pass the None.")

        cmd_create_member = "slb real %s %s %s %s" % (
                                                     argu['protocol'],
                                                     argu['member_id'],
                                                     argu['member_address'],
                                                     argu['member_port']
                                                     )


        cmd_add_rs_to_group = "slb group member %s %s %s" % (
                                                            argu['pool_id'],
                                                            argu['member_id'],
                                                            argu['member_weight']
                                                            )
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_create_member)
            self.run_cli_extend(base_rest_url, cmd_add_rs_to_group)


    def update_member(self, argu):
        """ Update a member"""

        if not argu:
            LOG.error("In update_member, it should not pass the None.")

        cmd_add_rs_to_group = "slb group member %s %s %s" % (
                                                            argu['pool_id'],
                                                            argu['member_id'],
                                                            argu['member_weight']
                                                            )
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_add_rs_to_group)


    def delete_member(self, argu):
        """ Delete a member"""

        if not argu:
            LOG.error("In delete_member, it should not pass the None.")

        cmd_delete_member = "no slb real %s %s" % (argu['protocol'], argu['member_id'])

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_delete_member)


    def create_health_monitor(self, argu):

        if not argu:
            LOG.error("In delete_member, it should not pass the None.")

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

        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_create_hm)
            self.run_cli_extend(base_rest_url, cmd_apv_attach_hm)

    def delete_health_monitor(self, argu):
        cmd_apv_detach_hm = ADCDevice.detach_hm_to_group(argu['pool_id'], argu['hm_id'])
        cmd_apv_no_hm = ADCDevice.no_health_monitor(argu['hm_id'])
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_apv_detach_hm)
            self.run_cli_extend(base_rest_url, cmd_apv_no_hm)


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

    def no_ha(self, vlan_tag):
        """ clear the HA configuration when delete_vip """

        if len(self.hostnames) == 1:
            LOG.debug("Only one machine, doesn't need to configure HA")
            return True

        interface_name = self.in_interface
        if vlan_tag:
            interface_name = "vlan." + vlan_tag

        cmd_apv_disable_cluster = ADCDevice.cluster_disable(interface_name)
        cmd_apv_clear_cluster_config = ADCDevice.cluster_clear_virtual_interface(interface_name)
        for base_rest_url in self.base_rest_urls:
            # disable the virtual cluster
            self.run_cli_extend(base_rest_url, cmd_apv_disable_cluster)

            # clear the configuration of this virtual ifname
            self.run_cli_extend(base_rest_url, cmd_apv_clear_cluster_config)


    def config_ha(self, vlan_tag, vip_address):
        """ set the HA configuration when delete_vip """

        if len(self.hostnames) == 1:
            LOG.debug("Only one machine, doesn't need to configure HA")
            return True

        interface_name = self.in_interface
        if vlan_tag:
            interface_name = "vlan." + vlan_tag

        priority = 1
        for base_rest_url in self.base_rest_urls:
            # define virtual ifname
            cmd_define_cluster_ifname = "cluster virtual ifname %s 100" % interface_name
            self.run_cli_extend(base_rest_url, cmd_define_cluster_ifname)

            cmd_define_cluster_vip = "cluster virtual vip %s 100 %s" % (interface_name, vip_address)
            self.run_cli_extend(base_rest_url, cmd_define_cluster_vip)

            priority += 10
            cmd_define_cluster_priority = "cluster virtual priority %s 100 %d" % (interface_name, priority)
            self.run_cli_extend(base_rest_url, cmd_define_cluster_priority)

            cmd_enable_cluster = "cluster virtual on 100 %s" % (interface_name)
            self.run_cli_extend(base_rest_url, cmd_enable_cluster)


    def get_cached_map(self, argu):
        return self.cache.get_interface_map_by_vip(argu['vip_id'])
