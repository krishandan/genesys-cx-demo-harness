"""Network & Devices: mimics a telco's device-management platform (ACS / mesh vendor API).

The design point of this module: a home network is inherently a graph of gateways,
radios, APs and devices — exactly the nested shape gx cannot return. So the module runs
fault detection internally and gx returns a flat *verdict*, not the raw topology. The
rich graph stays behind /v1/network.
"""
