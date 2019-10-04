#!/usr/bin/env python
from setuptools import setup, find_packages

setup(name='django-oscar-stripe',
      version='0.3',   # bump so that the build is obvious
      url='https://github.com/tangentlabs/django-oscar-stripe',
      author="David Winterbottom + forks",
      author_email="david.winterbottom@tangentlabs.co.uk",
      description="Stripe payment module for django-oscar",
      long_description=open('README.rst').read(),
      keywords="Payment, Stripe",
      license='BSD',
      packages=find_packages(exclude=['sandbox*', 'tests*']),
      include_package_data=True,
      install_requires=[
          'django-oscar>=0.6',
          'stripe>=1.12.0'
      ],
      # See http://pypi.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
          'Development Status :: 4 - Beta',
          'Environment :: Web Environment',
          'Framework :: Django',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: BSD License',
          'Operating System :: Unix',
          'Programming Language :: Python']
      )
