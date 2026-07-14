def classFactory(iface):
    from .lyssa_plugin import LyssaPlugin
    return LyssaPlugin(iface)
