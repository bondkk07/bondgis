def classFactory(iface):
    from .bondgis_plugin import BondGisPlugin
    return BondGisPlugin(iface)
