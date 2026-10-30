import time,json,psutil,sys
sys.path.insert(0,r'C:\_DEV\SportCamHUD')
from src.indicators import lean,gauge
p=psutil.Process(); out={}
cl={'x':50,'y':50,'size':5,'font_size':2.5,'form':'lean','source':'gyro','graphic':'bike','max_angle':30,'show_value':False,'show_label':False,'show_reference':True,'show_ticks':True}
cg={'x':50,'y':50,'form':'compass','size':5,'compass_rotation_mode':'rose','show_value':False}
def lr(v): return lean._render_lean_indicator(3840,2160,{'indicators':{'lean_indicator':cl}},'arial.ttf','lean_indicator',v,'°','LEAN',cl,2160,2,54,None,0,100,0,3,400,1)[0]
def gr(v): return gauge._render_compass_indicator(3840,2160,{},'arial.ttf','compass',v,'°','COMPASS',cg,2160,2,28,None,0,360,10,4,240,2,formatted_val='020')[0]
for name,clear,fn,cache in [('lean',lean.clear_lean_caches,lr,lean._LEAN_ROTATED_PATCH_CACHE),('compass',gauge.clear_compass_cache,gr,gauge._COMPASS_INDICATOR_CACHE)]:
 clear(); start_rss=p.memory_info().rss; t=time.perf_counter();samples=[]
 for i in range(600):
  fn(1.001+i*0.013)
  if i in (299,599): samples.append({'frames':i+1,'ms_per_frame':(time.perf_counter()-t)*1000/(i+1),'rss_delta_mib':(p.memory_info().rss-start_rss)/1048576,'entries':len(cache),'max_entries':cache.max_entries})
 out[name]=samples
print(json.dumps(out,indent=2));open(r'C:\GoPro\TO\p09\cache_probe.json','w').write(json.dumps(out,indent=2))
