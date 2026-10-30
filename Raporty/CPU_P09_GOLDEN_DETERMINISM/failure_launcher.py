if __name__ == '__main__':
 import sys,runpy
 sys.path.insert(0,r'C:\_DEV\SportCamHUD')
 from src.gui.qt._mixins.project_mixin import ProjectMixin
 original=ProjectMixin.export_readiness_state
 def forced(self):
  if self._project_map_export_target()[0] == 'cpu': return ('failed','syntetyczna awaria mapy P09')
  return original(self)
 ProjectMixin.export_readiness_state=forced
 sys.argv[0]=r'C:\_DEV\SportCamHUD\SportCamHUD.py'
 runpy.run_path(sys.argv[0],run_name='__main__')
