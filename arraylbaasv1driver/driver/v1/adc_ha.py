#!/usr/bin/python
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

import requests
import json

url = "https://192.168.5.223:9997/rest/apv/cli_extend"

def get_ha_group_id():
    payload = {
        "cmd": "show ha group id"
    }
    r = requests.post(url, json.dumps(payload), auth=('justtest', 'click1'), verify=False)
    if r.status_code != 200:
        msg = r.text
        return -1
    existed_set = set()
    result = r.text.split(':')[1][0:-1]
    for item in result.split('\\n'):
        if 'ha group id' in item:
            sub_item = item.split(' ')
            existed_set.add(int(sub_item[-1]))
    for i in range(1, 255):
        if i not in existed_set:
            return i
    return -1

"""
def config_ha(self, vlan_tag, interface, vip_address):
    if len(self.hostnames) == 1:
        LOG.debug("Only one machine, doesn't need to configure HA")
        return True

    ha_group_id = self._get_ha_group_id()
    if ha_group_id == -1:
        LOG.debug("Cannot get the group id")
        return False

    interface_name = self.in_interface
    if vlan_tag:
        interface_name = "vlan." + vlan_tag

    ha_clis = ["ha group id %s" % str(ha_group_id)]
    ha_clis.append("ha group fip %s %s %s" % (str(ha_group_id), vip_address, \
            interface_name))

    priority = 0
    for host in self.hostnames:
        priority += 10
        unit_name = "unit%d" % priority
        ha_clis.append("ha group priority %s %s %s" % (unit_name, str(ha_group_id),
            str(priority)))
    ha_clis.append()
    for host in self.hostnames:
        url = "https://" + host + ":9997/rest/apv/cli_extend"
        cmd_create_ha_group_id = "ha group id " + str(ha_group_id)
        payload = {
            "cmd": cmd_create_ha_group_id
        }
        r = requests.post(url, json.dumps(payload), auth=self.get_auth(), verify=False)
        if r.status_code != 200:
            msg = r.text
            raise ArrayADCException(msg, r.status_code)

def _get_ha_group_id(self):
    payload = {
        "cmd": "show ha group id"
    }
    existed_set = set()
    for base_rest_url in self.base_rest_urls:
        url = base_rest_url + '/cli_extend'
        r = requests.post(url, json.dumps(payload), auth=self.get_auth(), verify=False)
        if r.status_code != 200:
            msg = r.text
            raise ArrayADCException(msg, r.status_code)
        result = r.text.split(':')[1][0:-1]
        for item in result.split('\\n'):
            if 'ha group id' in item:
                sub_item = item.split(' ')
                existed_set.add(int(sub_item[-1]))
    LOG.debug("Now, it has existed(%s)", existed_set)
    for i in range(1, 255):
        if i not in existed_set:
            return i
    return -1



if __name__ == '__main__':
    i = get_ha_group_id()
    print i
"""

