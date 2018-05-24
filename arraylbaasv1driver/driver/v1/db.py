#
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

import time

from oslo_log import log as logging
from oslo_config import cfg

from neutron.plugins.ml2 import models
from neutron.plugins.ml2 import db

CMCC_DEFAULT_LEVEL = 1
CMCC_DEFAULT_NETWORK_TYPE = 'vlan'

LOG = logging.getLogger(__name__)

DB_OPTS = [
    cfg.StrOpt(
        'array_request_vlan_interval',
        default=100,
        help=('Interval in millisecond to request VLAN ID'
              'from database')
    ),
    cfg.StrOpt(
        'array_request_vlan_max_retries',
        default=10,
        help=('Maximum number to try to request vlan'
              'from database')
    ),
    cfg.StrOpt(
        'array_request_vlan_hostname',
        default=10,
        help=('Hostname of port binding')
    )
]

cfg.CONF.register_opts(DB_OPTS, "arraynetworks")

def _get_binding_level(context, port_id, level):
    result = None
    host = None
    if port_id:
        host = cfg.CONF.arraynetworks.array_request_vlan_hostname
        if not host:
            LOG.error("Unable to get host by port_id %(port_id)s", {'port_id': port_id})
            return result
        LOG.debug("For port %(port_id)s, got binding host %(host)s",
                {'port_id': port_id, 'host': host})
        result = (context.session.query(models.PortBindingLevel).
                  filter_by(port_id=port_id, host=host, level=level).
                  first())

        LOG.debug("For port %(port_id)s, level %(level)s, "
                  "got binding levels %(levels)s",
                  {'port_id': port_id,
                   'level': level,
                   'levels': result})
    return result

def _get_network_segment(context, segment_id, network_type):
    result = None
    if segment_id:
        result = (context.session.query(models.NetworkSegment).
                  filter_by(id=segment_id, network_type=network_type).
                  first())
        LOG.debug("For segment %(segment_id)s, network type %(network_type)s, "
                  "got binding levels %(networksegments)s",
                  {'segment_id': segment_id,
                   'network_type': network_type,
                   'networksegments': result})
    return result

def get_vlan_id_by_port_cmcc(context, port_id):
    vlan_id = None

    if not port_id:
        LOG.error("should provide the port_id")
        return None

    attempts = 0
    seconds_time = int(cfg.CONF.arraynetworks.array_request_vlan_interval) / 1000
    retries = int(cfg.CONF.arraynetworks.array_request_vlan_max_retries)
    while True:
        if attempts < retries:
            attempts += 1
        elif retries == 0:
            attempts = 0
        else:
            msg = ("Unable to get the vlan id. Exiting after "
                  "%(retries)s attempts") % {'retries': retries}
            LOG.error(msg)
            return None

        binding_level = _get_binding_level(context, port_id, CMCC_DEFAULT_LEVEL)
        if not binding_level:
            LOG.error("Unable to get binding_level using %(port_id)s", {'port_id': port_id})
            time.sleep(seconds_time)
            continue

        segment_id = binding_level.segment_id
        network_segment = _get_network_segment(context, segment_id, CMCC_DEFAULT_NETWORK_TYPE)
        if not network_segment:
            LOG.error("Unable to get network_segment using %(segment_id)s", {'segment_id': segment_id})
            time.sleep(seconds_time)
            continue
        else:
            vlan_id = network_segment.segmentation_id
            break

    return vlan_id

