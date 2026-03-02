// 延时刷新接口
// fun 方法，timesecond间隔时间 step间隔时间+布长，runonstart 要不要立即执行，maxloop 循环几次
var timetask = function(fun,timesecond,step,runonstart,maxloop){
    var timesecond = timesecond || 1;
        timesecond = timesecond;
    var runonstart = runonstart || false;
    var step = step || 1;
    var maxloop = maxloop || 4;
    var stop = stop || false
    var loopi = 0;
    var timeout;
    this.tasks=function(){
       if(loopi<=maxloop){
              if(fun)fun(loopi);
              timeout=setTimeout(tasks,timesecond * 1000);
              timesecond+=step;
       }else{
              console.log("最后一次刷新，停止查询被超提醒！");
       }
       loopi++;
    };
    this.end=function(){
       clearTimeout(timeout);
       maxloop=0;
       console.log("强制停止查询被超提醒！");
    }
    if(runonstart){
       this.tasks();
    }else{
       timeout=setTimeout(tasks,timesecond * 1000);
       loopi++;
       timesecond+=step;
    }
    return this;
  } 
  