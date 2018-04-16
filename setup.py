#!/usr/bin/env python
# flake8: noqa

from setuptools import setup, find_packages
from setuptools.command.install import install
import os

ARRAY_MAPPING_APV = '/usr/share/arraylbaasdriver/mapping_apv.json'
ARRAY_MAPPING_AVX = '/usr/share/arraylbaasdriver/mapping_avx.json'

class PostInstallCommand(install):
    def run(self):
        os.chmod(ARRAY_MAPPING_APV, 0777)
        os.chmod(ARRAY_MAPPING_AVX, 0777)
        install.run(self)

setup(
    name = "array-lbaasv1-driver",
    version = "1.0.0",
    packages = find_packages(),
    #package_dir = {'': 'arraylbaasv1driver'},

    author = "Array Networks",
    author_email = "wangli2@arraynetworks.com.cn",
    description = "Array Networks Openstack LBaaS v1 Driver Middleware",
    license = "Apache",
    keywords = "array apv slb load balancer openstack neutron lbaas",
    url = "http://www.arraynetworks.com.cn",

    classifiers = [
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet',
    ],

    cmdclass={
        'install': PostInstallCommand,
    },

    data_files=[('/etc/neutron/conf.d/neutron-server', ['etc/neutron/conf.d/neutron-server/arraynetworks.conf']),
                ('/usr/share/arraylbaasdriver', ['conf/mapping_apv.json', 'conf/mapping_avx.json']),],
)
