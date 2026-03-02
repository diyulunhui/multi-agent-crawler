var Url = "https://api.huaxiaguquan.com";
// var Url = "https://app.huaxiaguquan.com"; //测试服
var MyUrl = "https://quanyou.huaxiaguquan.com";
var qgUrl = "https://qgrading.huaxiaguquan.com";
var ysUrl = "https://autil.huaxiaguquan.com";
// var ysUrl = "http://192.168.14.29:8511";
var ysUrlNew = "https://uapi.hxguquan.com";
var AliUrl = "https://imgali.huaxiaguquan.com";
var HistoryUrl = "https://imgbj.huaxiaguquan.com";
var Cid = getCookie("cid")||"";
var Mid = getCookie("mid")||"";
var UserName = getCookie("username")||"";
var UserGrade = getCookie("usergrade")||"";
var UserPhone = getCookie("userPhone")||"";
// console.log("name:"+UserName);
// console.log("mid:"+Mid);
// console.log("cid:"+Cid);
// 除了登录页，其他页面加上一页url标识。为登录后返回上一页使用。

String.prototype.includes = function (str) {
    return this.indexOf(str) > -1
}

// 百度统计
var _hmt = _hmt || [];
(function () {
    var hm = document.createElement("script");
    hm.src = "https://hm.baidu.com/hm.js?300984d16dcfa32615bf8823deac5af7";
    var s = document.getElementsByTagName("script")[0];
    s.parentNode.insertBefore(hm, s);
})();

// 获取cookie中的cid 和mid
function getCookie(name) {
    var prefix = name + "=";
    var start = document.cookie.indexOf(prefix);
    if (start == -1) {
        return "";
    }

    var end = document.cookie.indexOf(";", start + prefix.length);
    if (end == -1) {
        end = document.cookie.length;
    }
    var value = document.cookie.substring(start + prefix.length, end);
    try {
        typeof JSON.parse(value) == 'object'
        value = JSON.parse(value);
    } catch (e) {

    }

    return value;
}
// 设置cookie
function setCookie(cname, cvalue, exminute) {
    try {
        typeof cvalue == 'object'
        cvalue = JSON.stringify(cvalue);
    } catch (e) {

    }
    var str = cname + "=" + cvalue+"; path=/";
    //不传时不设定过期时间，浏览器关闭时cookie自动消失
    if (exminute) {
        var date = new Date();
        date.setTime(date.getTime() + (exminute * 60 * 1000));
        str += "; expires=" + date.toGMTString();
    }
    document.cookie = str;
    // console.log(str);
}
//清除cookie  
function clearCookie(name) {
    setCookie(name, "", -1);
}
// 重新获取cid
function updateCid() {
    $.ajax({
        url: Url + "/v3/auth/cid.jsp?jscall=?",
        type: "post",
        data: {
            "app": "H5",
            "v": "1.0.0"
        },
        dataType: "jsonp",
        contentType: 'application/x-www-form-urlencoded',
        success: function (data) {
            if (data.error == "0") {
                // 给cookie里的cid赋值
                setCookie("cid", data.cid);
                console.log(getCookie("cid"));
                Cid = data.cid;
                // 删掉cookie里的mid 
                if (Mid) {
                    clearCookie("mid");
                }
                console.log("重新保存Cid：" + data.cid);
            } else {
                console.log(data.error);
            }
        },
        error: function (error) {
            console.log("获取cid接口：", error);
        }
    });
}
// 获取用户信息
function user() {
    var me = this;
    $.ajax({
        url: Url + "/v3/my/credit.jsp?jscall=?",
        type: "post",
        data: {
            "cid": Cid
        },
        dataType: "jsonp",
        contentType: 'application/x-www-form-urlencoded',
        success: function (data) {
            // console.log(data);
            if (data.error == "0") {
                UserName = data.MM_NAME;
                console.log('获取账号等级：', data.MM_VIPGRADEMARK);
                if (data.MM_VIPGRADEMARK == "VIP") {
                    $(".my-user").append('<img src=""+AliUrl+"/app/v3/images/head/vip-1.svg" />');
                } else if (data.MM_VIPGRADEMARK == "VVIP") {
                    $(".my-user").append('<img src=""+AliUrl+"/app/v3/images/head/vvip-1.svg" />');
                } else if (data.MM_VIPGRADEMARK == "SVIP") {
                    $(".my-user").append('<img src=""+AliUrl+"/app/v3/images/head/svip-1.svg" />');
                } else {
                    if (data.MM_VIPGRADEMARK != "") {
                        $(".my-user").append('<i class="user-grade">' + data.MM_VIPGRADEMARK + '</i>');
                    }
                }
                setCookie("username", data.MM_NAME);
                setCookie("usergrade", data.MM_VIPGRADEMARK);
                $(".user-name").text(data.MM_NAME);
                console.log("等级：" + data.MM_VIPGRADEMARK);

                // 竞拍占用额度 Bidusedcredit  结算占用额度 buyedcredit  总额度totalcredit   可用额度freecredit
                // 可用额度
                $("#usableMoney").text(data.freecredit);
                // 已用额度
                $("#usedMoney").text(parseInt(data.buyedcredit) + parseInt(data.bidusedcredit));
            } else {
                // console.log(data.error);
                if (data.error.substring(0, 5) == "-1020") {
                    if (Mid) {
                        // console.log(getCookie("mid"));
                        clearCookie("mid");
                        Mid = "";
                    }
                }
            }
        },
        error: function (_error) {
            console.log("个人信息接口", _error);
        }
    });
}
// 加价幅度
function priceRange(price) {
    if (price < 1000) {
        return 20;
    } else if (price < 2000) {
        return 50;
    } else if (price < 5000) {
        return 100;
    } else if (price < 10000) {
        return 200;
    } else if (price < 50000) {
        return 500;
    } else if (price < 100000) {
        return 1000;
    } else if (price < 500000) {
        return 2000;
    } else if (price < 1000000) {
        return 5000;
    } else if (price < 2000000) {
        return 10000;
    } else if (price < 5000000) {
        return 50000;
    } else if (price >= 5000000) {
        return 100000;
    }
}
//检查价格是否复合阶梯要求
function verifyPrice(p) {
    var ret = false;
    if (p < 20) {
        ret = false;
    } else if (p < 1000) {
        ret = (p % 20 == 0) ? true : false;
    } else if (p < 2000) {
        ret = ((p - 1000) % 50) == 0 ? true : false;
    } else if (p < 5000) {
        ret = ((p - 2000) % 100) == 0 ? true : false;
    } else if (p < 10000) {
        ret = ((p - 5000) % 200) == 0 ? true : false;
    } else if (p < 50000) {
        ret = ((p - 10000) % 500) == 0 ? true : false;
    } else if (p < 100000) {
        ret = ((p - 50000) % 1000) == 0 ? true : false;
    } else if (p < 500000) {
        ret = ((p - 100000) % 2000) == 0 ? true : false;
    } else if (p < 1000000) {
        ret = ((p - 500000) % 5000) == 0 ? true : false;
    } else if (p < 2000000) {
        ret = ((p - 1000000) % 10000) == 0 ? true : false;
    } else if (p < 5000000) {
        ret = ((p - 2000000) % 50000) == 0 ? true : false;
    } else {
        ret = ((p - 5000000) % 100000) == 0 ? true : false;
    }
    return ret;
}
//根据当前价格加一口
function getNextPlusPrice(p) {
    if (p < 20) {
        return 20;
    } else if (p < 1000) {
        return (parseInt(p / 20 + 1) * 20);
    } else if (p < 2000) {
        return (parseInt((p - 1000) / 50 + 1) * 50 + 1000);
    } else if (p < 5000) {
        return (parseInt((p - 2000) / 100 + 1) * 100 + 2000);
    } else if (p < 10000) {
        return (parseInt((p - 5000) / 200 + 1) * 200 + 5000);
    } else if (p < 50000) {
        return (parseInt((p - 10000) / 500 + 1) * 500 + 10000);
    } else if (p < 100000) {
        return (parseInt((p - 50000) / 1000 + 1) * 1000 + 50000);
    } else if (p < 500000) {
        return (parseInt((p - 100000) / 2000 + 1) * 2000 + 100000);
    } else if (p < 1000000) {
        return (parseInt((p - 500000) / 5000 + 1) * 5000 + 500000);
    } else if (p < 2000000) {
        return (parseInt((p - 1000000) / 10000 + 1) * 10000 + 1000000);
    } else if (p < 5000000) {
        return (parseInt((p - 2000000) / 50000 + 1) * 50000 + 2000000);
    } else {
        return (parseInt((p - 5000000) / 100000 + 1) * 100000 + 5000000);
    }
}
//给定价格减一口
function getNextMinusPrice(p) {
    if (p <= 20) {
        return 20;
    } else if (p <= 1000) {
        return (Math.ceil(p / 20 - 1) * 20);
    } else if (p <= 2000) {
        return (Math.ceil((p - 1000) / 50 - 1) * 50 + 1000);
    } else if (p <= 5000) {
        return (Math.ceil((p - 2000) / 100 - 1) * 100 + 2000);
    } else if (p <= 10000) {
        return (Math.ceil((p - 5000) / 200 - 1) * 200 + 5000);
    } else if (p <= 50000) {
        return (Math.ceil((p - 10000) / 500 - 1) * 500 + 10000);
    } else if (p <= 100000) {
        return (Math.ceil((p - 50000) / 1000 - 1) * 1000 + 50000);
    } else if (p < 500000) {
        return (parseInt((p - 100000) / 2000 - 1) * 2000 + 100000);
    } else if (p < 1000000) {
        return (parseInt((p - 500000) / 5000 - 1) * 5000 + 500000);
    } else if (p < 2000000) {
        return (parseInt((p - 1000000) / 10000 - 1) * 10000 + 1000000);
    } else if (p < 5000000) {
        return (parseInt((p - 2000000) / 50000 - 1) * 50000 + 2000000);
    } else {
        return (parseInt((p - 5000000) / 100000 - 1) * 100000 + 5000000);
    }
}
// 金额添加千分位
function addCommas(val) {
    if (val) {
        while (/(\d+)(\d{3})/.test(val.toString())) {
            val = val.toString().replace(/(\d+)(\d{3})/, '$1' + ',' + '$2');
        }
        return val;
    } else {
        return 0;
    }
}
// 超小图
function miniImg(img) {
    return img.split('.jpg')[0] + '_90_' + '.jpg';
}
// 小图
function smallImg(img) {
    if (img == undefined || img.indexOf("undefined") > -1) {
        return "" + AliUrl + "/app/v3/images/icon/img-error.png";
    } else {
        return img.split('.jpg')[0] + '_160_' + '.jpg';
    }
}
// 中图
function middleImg(img) {
    return img.split('.jpg')[0] + '_450_' + '.jpg';
}
// 获取url参数
function getQueryString(name) {
    var reg = new RegExp("(^|&)" + name + "=([^&]*)(&|$)");
    var r = window.location.search.substr(1).match(reg);
    if (r != null) return unescape(r[2]); return null;
}
// 判断是星期几
function getWeek(dateString) {
    if (dateString) {
        var todaysDate = new Date();
        var d = new Date(dateString.replace(/-/g, "/"));
        if (d.setHours(0, 0, 0, 0) == todaysDate.setHours(0, 0, 0, 0)) {
            return "<i class='iconfont'>&#xe67c;</i> 今天" + dateString.slice(10, 16);
        } else {
            var dateArray = dateString.slice(0, 10).replace(/-/g, "/");
            var date = new Date(dateArray);
            // console.log(date.getDay());
            var week = "周" + "日一二三四五六".charAt(date.getDay());
            return dateString.slice(5, 10) + " (" + week + ") " + dateString.slice(10, 16);
        }
    } else {
        return "**-** (星期*) **:**";
    }
};
// 判断是否是今天
function today(time) {
    var d = new Date(time.replace(/-/g, "/"));
    var todaysDate = new Date();
    if (d.setHours(0, 0, 0, 0) == todaysDate.setHours(0, 0, 0, 0)) {
        return true;
    } else {
        return false;
    }
}
// 倒计时
function countDown(time) {
    var nowtime = new Date(),  //获取当前时间
        endtime = new Date(time.replace(/-/g, '/'));  //定义结束时间
    var lefttime = endtime.getTime() - nowtime.getTime(); //距离结束时间的毫秒数
    var day = Math.floor(lefttime / (1000 * 60 * 60) / 24),
        lefth = Math.floor(lefttime / (1000 * 60 * 60) % 24),  //计算小时数
        leftm = Math.floor(lefttime / (1000 * 60) % 60),  //计算分钟数
        lefts = Math.floor(lefttime / 1000 % 60),  //计算秒数
        stillDay = lefth + "小时" + leftm + "分" + lefts + "秒";

    if (day > 0) {
        stillDay = day + "天 " + stillDay;
    }
    if (lefttime <= 0) {
        return "0小时0分0秒";
    }
    return stillDay;  //返回倒计时的字符串
}
function countDown2(time) {
    var nowtime = new Date(),  //获取当前时间
        endtime = new Date(time.replace(/-/g, '/'));  //定义结束时间
    var lefttime = endtime.getTime() - nowtime.getTime(); //距离结束时间的毫秒数
    var day = Math.floor(lefttime / (1000 * 60 * 60) / 24),
        lefth = Math.floor(lefttime / (1000 * 60 * 60) % 24),  //计算小时数
        leftm = Math.floor(lefttime / (1000 * 60) % 60),  //计算分钟数
        lefts = Math.floor(lefttime / 1000 % 60),  //计算秒数
        stillDay = (lefth < 10 ? '0' : '') + lefth + ":" + (leftm < 10 ? '0' : '') + leftm + ":" + (lefts < 10 ? '0' : '') + lefts;

    if (day > 0) {
        stillDay = day + "天 " + stillDay;
    }
    if (lefttime <= 0) {
        return "<i class='iconfont'>&#xe67c;</i> 0:0:0";
    }
    return "<i class='iconfont'>&#xe67c;</i> " + stillDay;  //返回倒计时的字符串
}
// 小写数字变大写 
var ChineseArr = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];
function chineseNum(number) {
    var num = parseInt(number - 1);
    return ChineseArr[num];
}
// 时间格式化
function getNowDate(myDate) {
    var year = myDate.getFullYear(); //获取当前年
    var mon = myDate.getMonth() + 1; //获取当前月
    var date = myDate.getDate(); //获取当前日
    var hours = myDate.getHours(); //获取当前小时
    var minutes = myDate.getMinutes(); //获取当前分钟
    var seconds = myDate.getSeconds(); //获取当前秒
    var now = '';
    now = year + "-" + zeroDay(mon) + "-" + zeroDay(date) + " " + zeroDay(hours) + ":" + zeroDay(minutes) + ":" + zeroDay(seconds);
    return now;
}

// 日期补零
function zeroDay(data) {
    if (data < 10) {
        return "0" + data;
    } else {
        return data;
    }
}
// 判断已经结标期次
function endDay(time) {
    var d = new Date(time.replace(/-/g, "/"));
    var todaysDate = new Date();
    if (d.setHours(0, 0, 0, 0) < todaysDate.setHours(0, 0, 0, 0)) {
        return true;
    } else {
        return false;
    }
}
if (!getCookie('cid')) {
    console.log("没有cid")
    updateCid();
}

