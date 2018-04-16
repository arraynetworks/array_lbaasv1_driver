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
from arraylbaasv1driver.driver.v1.adc_map import service_group_lb_method
from arraylbaasv1driver.driver.v1.adc_cache import LogicalAPVCache

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

        # create vip
        self._create_vip(argu['vip_id'],
                         argu['vlan_tag'],
                         argu['vip_address'],
                         argu['netmask'],
                         argu['interface_mapping']
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
                    interface_mapping
                   ):
        """ create vip"""

        interface_name = self.in_interface

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
        max_conn = connection_limit
        if max_conn == -1:
            max_conn = 0
        payload = {
            "service_name": vip_id,
            "vip": vip_address,
            "vport": protocol_port,
            "max_conn": max_conn
        }

        for base_rest_url in self.base_rest_urls:
            url = base_rest_url + '/loadbalancing/slb/vs/protocols/' + \
                protocol + 'VirtualService'
            LOG.debug("create_listener URL: --%s--", url)
            LOG.debug("create_listener payload: --%s--", payload)
            r = requests.post(url, data=json.dumps(payload), auth=self.get_auth(),
                          verify=False)
            if r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


    def _delete_vs(self, vip_id, protocol):
        for base_rest_url in self.base_rest_urls:
            url = '%s/loadbalancing/slb/vs/protocols/%sVirtualService/%s' % (
                   base_rest_url, protocol, vip_id)
            LOG.debug("delete_vs URL: --%s--", url)
            r = requests.delete(url, auth=self.get_auth(), verify=False)
            if r.status_code == 404:
                pass
            elif r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


    def _create_policy(self,
                       pool_id,
                       vip_id,
                       session_persistence_type,
                       lb_algorithm,
                       cookie_name):
        """ Create SLB policy """

        (algorithm, first_choice_method, policy) = service_group_lb_method(lb_algorithm,
                                                   session_persistence_type)
        payload = {
            "name": vip_id,
            "src": vip_id,
            "dst": pool_id
        }
        if policy == 'PC':
            payload['cookie_name'] = cookie_name
        for base_rest_url in self.base_rest_urls:
            url = base_rest_url + '/loadbalancing/slb/policy/types/' + policy + 'Policy'
            LOG.debug("create_policy URL: --%s--", url)
            LOG.debug("create_policy payload: --%s--", payload)
            r = requests.post(url, data=json.dumps(payload), auth=self.get_auth(),
                              verify=False)
            if r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


    def _delete_policy(self, vip_id, session_persistence_type, lb_algorithm):
        """ Delete SLB policy """
        (_, _, policy) = service_group_lb_method(lb_algorithm,
                                                   session_persistence_type)
        for base_rest_url in self.base_rest_urls:
            url = base_rest_url + '/loadbalancing/slb/policy/types/' + policy + 'Policy/' + vip_id
            LOG.debug("delete policy URL: --%s--", url)
            r = requests.delete(url, auth=self.get_auth(), verify=False)
            if r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


    def create_group(self, argu):
        """ Create SLB group in lb-pool-create"""

        if not argu:
            LOG.error("In create_group, it should not pass the None.")

        (algorithm, first_choice_method, policy) = service_group_lb_method(argu['lb_algorithm'],
                                                   None)
        payload = {
            "group_name": argu['pool_id'],
        }
        if first_choice_method:
            payload['first_choice_method'] = first_choice_method

        for base_rest_url in self.base_rest_urls:
            url = '%s/loadbalancing/slb/group/methods/%sGroup' % (base_rest_url, algorithm)
            LOG.debug("create_group URL: --%s--", url)
            LOG.debug("create_group payload: --%s--", payload)
            r = requests.post(url, data=json.dumps(payload), auth=self.get_auth(),
                          verify=False)
            if r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


    def delete_group(self, argu):
        """Delete SLB group in lb-pool-delete"""

        if not argu:
            LOG.error("In delete_group, it should not pass the None.")

        (algorithm, first_choice_method, policy) = service_group_lb_method(argu['lb_algorithm'],
                                                   None)
        for base_rest_url in self.base_rest_urls:
            url = '%s/loadbalancing/slb/group/methods/%sGroup/%s' % (
                base_rest_url, algorithm, argu['pool_id'])
            LOG.debug("delete_group URL: --%s--", url)
            r = requests.delete(url, auth=self.get_auth(), verify=False)
            if r.status_code == 404:
                pass
            elif r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)


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

        hm_type = argu['hm_type']
        if hm_type == 'PING':
            hm_type = 'ICMP'
        if hm_type == 'HTTP' or hm_type == 'HTTPS':
            payload = {
                "hc_name": argu['hm_id'],
                "type": argu['hm_type'],
                "interval": argu['hm_delay'],
                "hc_up": argu['hm_max_retries'],
                "hc_down": argu['hm_max_retries'],
                "timeout": argu['hm_timeout'],
                "http_method": argu['hm_http_method'],
                "url": argu['hm_url'],
                'expected_codes': argu['hm_expected_codes']
            }
        else:
            payload = {
                "hc_name": argu['hm_id'],
                "type": argu['hm_type'],
                "interval": argu['hm_delay'],
                "hc_up": argu['hm_max_retries'],
                "hc_down": argu['hm_max_retries'],
                "timeout": argu['hm_timeout']
            }
        for base_rest_url in self.base_rest_urls:
            url = base_rest_url + '/loadbalancing/slb/healthcheck/GroupHealthCheck'
            LOG.debug("create_health_monitor URL: --%s--", url)
            LOG.debug("create_health_monitor payload: --%s--", payload)
            r = requests.post(url, data=json.dumps(payload), auth=self.get_auth(),
                verify=False)
            if r.status_code != 200:
                msg = r.text
                raise ArrayADCException(msg, r.status_code)

        cmd_associate_hc_with_group = "slb group health " + argu['pool_id'] + " " + argu['hm_id']
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_associate_hc_with_group)

    def delete_health_monitor(self, argu):
        cmd_disassociate_hc_with_group = "no slb group health " + argu['pool_id'] + " " + argu['hm_id']
        cmd_delete_hc = "no slb health  " + argu['hm_id']
        for base_rest_url in self.base_rest_urls:
            self.run_cli_extend(base_rest_url, cmd_disassociate_hc_with_group)
            self.run_cli_extend(base_rest_url, cmd_delete_hc)


    def run_cli_extend(self, base_rest_url, cmd):
        url = base_rest_url + '/cli_extend'
        payload = {
            "cmd": cmd
        }
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

        for base_rest_url in self.base_rest_urls:
            # disable the virtual cluster
            cmd_disable_cluster = "cluster virtual on 100 %s" % (interface_name)
            self.run_cli_extend(base_rest_url, cmd_disable_cluster)

            # clear the configuration of this virtual ifname
            cmd_clear_cluster_ifname = "cluster virtual ifname %s 100" % interface_name
            self.run_cli_extend(base_rest_url, cmd_clear_cluster_ifname)



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