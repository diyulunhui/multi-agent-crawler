function Index() {
    this.Cid = Cid;
    this.Mid = Mid;
    this.chartroomUpdateFlg = false;
    this.KanKan = 1; //调用4次精品推荐接口
    this.KanKanHtml = ""; //猜你喜欢html
    this.MyLabel = JSON.parse(localStorage.getItem("mylabel")); //我定义的标签
    this.BaseLabel = getCookie("baseLabel"); //我定义的标签
    this.HotSearchList = ["咸丰重宝", "袁大头", "康熙通宝", "刀币", "布币"];
    this.TimeOver = false;//聊天室刷新超时
    this.GroupId = "";//聊天室id
    this.AdvertArr = ["https://imgali.huaxiaguquan.com/pic/2026/0209/1571242793358266361w2711h4061_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0209/1571254589603014271w2359h4450_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0210/1571933270285825051w3493h3493_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0210/1571938601480993051w3451h3451_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0210/1571939138828994371w3451h3410_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0210/1571937853999287891w3110h3110_160_.jpg",
        "https://imgali.huaxiaguquan.com/pic/2026/0210/1571940618138324571w3110h3110_160_.jpg"]; //活动图片列表
    this.WinningList = [
        "153***3930",
        "187***4135",
        "150***8761",
        "136***5034",
        "187***3028",
        "176***6663",
        "136***5726",
        "152***8128",
        "187***6133",
        "136***6321",
        "150***0437",
        "150***3463",
        "136***5321",
        "150***7181",
        "138***2120",
        "153***0504",
        "133***2332",
        "137***0777",
        "135***6515",
        "156***7539"];
};
Index.prototype.init = function () {
    // 加载组件
    $(".head").load("../public/header-index.html?21", function () {
        $('.nav-bar .nav-home').addClass('active');
    });
    $(".foot").load("../public/footer.html?13");
    // 我的关注列表
    if (this.Mid) {
        $("#collectionBox").load("../public/collectionList.html", function () {
            collection.todayList(6);
        });
        // 自选钱币标签
        this.myLabel();
    }
    // 显示转账优化 提醒框
    // if (localStorage.getItem("alertDialog") != "true") {
    //     $("#dialog").show();
    // }
    // 显示费率变化 提醒框
    if (localStorage.getItem("alertDialog2") != "true") {
        $("#dialog2").show();
    }
    // 默认隐藏登录框
    $("#loginFixed").hide();

    $("#today").text(zeroDay(new Date().getDate()));
    $("#curMonth").text(zeroDay(new Date().getMonth() + 1) + "月");
    var html = "";
    $.each(this.HotSearchList, function (index, val) {
        html += "<a href=\"javascript:;\">" + val + "</a>";
    });
    $("#hotSearchList").html(html);
    //提示
    // this.alert();
    // 点击事件
    this.clickEvent();
    // 广告图
    this.banner();
    // 聊天室(开放聊天室一定要打开！！！)
    // this.getChatRoom();
    // 下面是聊天室实时更新代码
    if (typeof (AuctionItemsCache) != 'undefined') {
        console.log("开启聊天室更新");
        this.chartroomUpdate();
    }
    // 精品推荐
    this.getYoulike();
    // 专场
    this.getAuctionField();
    // 新闻
    this.news();
    // 图库
    this.map();
    // 图表
    this.echart();
    //中奖名单轮播
    // this.winningScroll();
    // 专场活动轮播
    var AdvertArr = ''
    $.each(this.AdvertArr, function (index, val) {
        AdvertArr += '<li><a href="javascript:;"><img class="chatImg" src="' + val + '" alt=""></a></li>'
    })
    $('.chat-pic').html(AdvertArr);
    setTimeout(function () {
        $("#roll").scrollForever();
    }, 500);
    $('.chat-pic').on('click', function () {
        window.location.href = 'goods-list.html?gid=74568'
    })
};
Index.prototype.winningScroll = function () {
    let html = '';
    $.each(this.WinningList, function (index, val) {
        html += '<li>恭喜<em class="red2">' + val + '</em>中奖</li>'
        console.log(index);
    })
    $("#winningList ul").html(html);
    $("#winningList").scrollForever();
};
// 点击事件
Index.prototype.clickEvent = function () {
    var me = this;
    // 跳转站内信
    $(".attention-letter ul a").click(function () {
        if (Mid) {
            var id = $(this).attr("data-id");
            window.location.href = "letter.html?sendid=" + id;
        } else {
            window.location.href = "login.html";
        }
    });
    // 点击添加标签按钮
    $("#addLabel").click(function () {
        if (me.Mid) {
            $(".input-label").show();
            $(this).hide();
            $("#complete").hide();
            $("#inputLabel").val("");
        } else {
            window.location.href = "login.html";
        }

    });
    // 点击编辑标签按钮
    $("#editLabel").click(function () {
        if ($("#complete").css("display") == "none") {
            $("#myLabel a").addClass("label-edit");
            $("#complete").show();
            $("#edit,#addLabel,.input-label").hide();
            console.log(me.MyLabel.length);
        } else {
            $("#myLabel a").removeClass("label-edit");
            $("#edit,#addLabel").show();
            $("#complete").hide();
        }
    });
    // 完成添加标签，点对勾
    $("#completeLabel").click(function () {
        var labelVal = $("#inputLabel").val();
        if (labelVal.replace(/\s+/g, "") != "") {
            console.log(me.MyLabel);
            me.MyLabel.push({ "mid": me.Mid, "labelName": labelVal, "labelId": "-1", "labelType": 0 });
            $(".input-label").hide();
            $("#addLabel,#editLabel,#edit").show();
            localStorage.setItem("mylabel", JSON.stringify(me.MyLabel));
            $("#myLabel").append("<a href=\"javascript:;\"><em>" + labelVal + "</em> <i class=\"iconfont close\">&#xe630;</i></a>");
        } else {
            Toast("请输入有效标签");
        }
    });
    // 点击删除当前自定义标签
    $(".search-label").on("click", "a", function () {
        var that = $(this);
        if ($(this).attr("class") == "label-edit") {
            var thisVal = $(this).find("em").text();
            $.each(me.MyLabel, function (index, val) {
                if (val && val.labelName == thisVal) {
                    me.delMyLabel(thisVal, index, that);
                }
            })
        } else {
            var searchVal = $(this).find("em").text();
            var searchId = $(this).attr("data-id");
            console.log(searchId);
            if (searchId == "null" || searchId == null) {
                window.location.href = "search-list.html?stype=auctioning&skey=" + escape(searchVal);
            } else {
                window.location.href = "search-list.html?stype=auctioning&skey=" + escape(searchVal) + "&" + "gtype=" + searchId;
            }
        }
    });
    // 点击价格查询按钮
    $("#priceSearch").click(function () {
        var searchVal = $("#priceSearchVal").val();
        window.location.href = "search-list.html?stype=history&skey=" + escape(searchVal);
    });
    // 更多标签
    $("#more").click(function () {
        if ($("#myLabel").attr("class") == "my-label") {
            $("#myLabel").addClass("open-label");
            $(this).html("收起 <i class=\"iconfont\">&#xe6e3;</i>");
        } else {
            $("#myLabel").removeClass("open-label");
            $(this).html("更多 <i class=\"iconfont\">&#xe601;</i>");
        }
    });
    $("#showClassify").click(function () {
        // Toast("暂未开放功能");
        var p1 = $("#p1").val();
        var p2 = $("#p2").val();
        window.location.href = "search-list.html?stype=history&p1=" + p1 + "&p2=" + p2;
    });
    $("#hotSearchList").on("click", "a", function () {
        var searchVal = $(this).text();
        window.location.href = "search-list.html?stype=history&skey=" + escape(searchVal);
    });
    // 关闭聊天室提示
    $("#chatRoomTip").on("click", ".close", function () {
        $("#chatRoomTip").hide();
    })

    $("#loginFixed .close").on('click', function () {
        $("#loginFixed").hide()
    })
    $("#loginFixed button").on('click', function (e) {
        location.href = $(this).attr('data-type') + '.html'
    })

    // $("#dialog button").on('click', function (e) {
    //     console.log($(this).attr('class'))
    //     if ($(this).attr('class') == 'confirm') {
    //         localStorage.setItem("alertDialog", true);
    //     }
    //     $("#dialog").hide()
    // })

    $("#dialog2 button").on('click', function (e) {
        if ($(this).attr('class') == 'confirm') {
            localStorage.setItem("alertDialog2", true);
        }
        $("#dialog2").hide()
    })
};
Index.prototype.getItemName = function (id) {
    // console.log(AuctionItemsCache);
    if (AuctionItemsCache[id]) {
        return AuctionItemsCache[id][0];
    } else {
        return '';
    }
}
Index.prototype.getItemPic = function (id) {
    // console.log(AuctionItemsCache);
    if (AuctionItemsCache[id]) {
        return smallImg(AuctionItemsCache[id][1]);
    } else {
        return '';
    }
}
// 删除自选钱币标签
Index.prototype.delMyLabel = function (label, index, that) {
    var me = this;
    $.ajax({
        url: qgUrl + "/userVifLabel/delUserVifLabel",
        type: "get",
        data: {
            "cid": getCookie("cid"),
            "label": label,
        },
        success: function success(data) {
            // console.log(data.msg);
            if (data.code == 200) {
                me.MyLabel.splice(index, 1);
                localStorage.setItem("mylabel", JSON.stringify(me.MyLabel));
                that.hide();
                if (me.MyLabel.length == 0) {
                    $("#editLabel").hide();
                    $("#addLabel").show();
                }
            } else {
                Toast(data.msg);
            }
        },
        error: function error(_error) {
            Toast(data.msg);
        }
    });
};
// 自选钱币标签
Index.prototype.myLabel = function () {
    var me = this;
    console.log("自定义标签：", me.MyLabel);
    var labelHtml = "";
    if (me.MyLabel == "null" || me.MyLabel == null) {
        $.ajax({
            url: qgUrl + "/userVifLabel/getUserVifLabel",
            type: "get",
            data: {
                "cid": getCookie("cid")
            },
            success: function success(data) {
                console.log(data.code);
                if (data.code == 200) {
                    me.MyLabel = data.data.reverse();
                    if (me.MyLabel.length > 0) {
                        $("#editLabel").show();
                    }
                    localStorage.setItem("mylabel", JSON.stringify(me.MyLabel));
                    $.each(me.MyLabel, function (index, val) {
                        labelHtml += "<a href=\"javascript:;\"><em>" + val.labelName + "</em><i class=\"iconfont close\">&#xe630;</i></a>";
                    });
                } else if (data.code == 204) {
                    me.MyLabel = [];
                    localStorage.setItem("mylabel", JSON.stringify(me.MyLabel));
                } else {
                    console.log(data.error);
                }
                $("#myLabel").html(labelHtml);
            },
            error: function error(_error) {
                console.log("自选钱币标签", _error);
            }
        });
    }
    else {
        if (me.MyLabel.length != 0) {
            $("#editLabel").show();
        }
        $.each(me.MyLabel, function (index, val) {
            labelHtml += "<a href=\"javascript:;\"><em>" + val.labelName + "</em><i class=\"iconfont close\">&#xe630;</i></a>";
        });
        $("#myLabel").html(labelHtml);
    }
};
// 广告图
Index.prototype.banner = function () {
    var me = this;
    $.ajax({
        url: Url + "/v3/kankan/pics.jsp?jscall=?",
        type: "get",
        dataType: "jsonp",
        contentType: 'application/x-www-form-urlencoded',
        success: function success(data) {
            // console.log(data);
            if (data.error == "0") {
                var html = "";
                var link = "";
                var pagination = '';
                // data.guangao.push({
                //     imgurl
                //         :
                //         "https://mhx.huaxiaguquan.com/banner/shouxinBanner.png?1",
                //     linktype
                //         :
                //         "1",
                //     linkurl
                //         :
                //         "https://www.shouxinwenpai.com"
                // })
                // 暂时过滤 book3 的广告图
                for (var i = 0; i < data.guangao.length; i++) {

                    var index = data.guangao[i].imgurl.indexOf("//imgali.huaxiaguquan.com/pic/2024/0808/2024080814261451999254.jpg")
                    if (index > -1) {
                        data.guangao.splice(i, 1); // 删除索引处的元素
                    }
                }

                for (var i = 0; i < data.guangao.length; i++) {
                    var val = data.guangao[i];
                    link = val.linkurl;
                    if (val.imgurl.includes("2025120521042015515164")) {
                        var Link = "https://mp.weixin.qq.com/s/t4mLTD-ksCVxNMLUVpMjZA";

                        console.log(Link)
                        html += "<a target=\"_blank\" href=\"" + Link + "\"><img src=\"" + val.imgurl + "\" alt=\"\"></a>"

                    }
                    if (link.indexOf("https://mhx.huaxiaguquan.com/") != -1) {
                        if (link.indexOf('chatroom-list-custom.html') == -1) {
                            link = link.replace("https://mhx.huaxiaguquan.com/", "");
                        }
                    } else if (link.indexOf("//mhx.huaxiaguquan.com/") != -1) {
                        link = link.replace("//mhx.huaxiaguquan.com/", "");
                    } else if (link.indexOf("//www.shouxinwenpai.com/?BSvt-rI-irO1o7qtiduKLA#") != -1) {
                        link = link.replace("//www.shouxinwenpai.com/?BSvt-rI-irO1o7qtiduKLA#", "//www.shouxinwenpai.com/goods-list.html?gid=")
                    }
                    // 书城商品详情
                    if (link.indexOf("/#/pages/index/") != -1) {
                        link = link.split("/#/pages/index/")[1];
                        link = link.replace("goods-detail?", "bookstore/book-detail.html?");
                    }

                    if (val.imgurl.indexOf('imghz.huaxiaguquan.com')) {
                        val.imgurl = val.imgurl.replace('imghz.huaxiaguquan.com', 'hximg.oss-cn-hangzhou.aliyuncs.com')
                    }
                    if (val.imgurl.indexOf("2022051619591408231381.jpg") == -1) {
                        // html += "<div class=\"swiper-slide\"><a target=\"_blank\" href=\"" + link + "\"><img src=\"" + val.imgurl + "\" alt=\"\"></a></div>";
                        // 筛掉图书链接
                        // if (val.imgurl != "//hximg.oss-cn-hangzhou.aliyuncs.com/pic/2024/0425/2024042509393490256220.jpg") {
                        html += "<a target=\"_blank\" href=\"" + link + "\"><img src=\"" + val.imgurl + "\" alt=\"\"></a>"
                        // }
                    }

                    console.log(val.imgurl.includes("2025120521042015515164"));


                    pagination += "<span></span>"
                }
                // $.each(data.guangao, function (index, val) {

                // });
                $(".banner .container").html(html);
                $(".banner .pagination").html(pagination);
                $(".banner>.pagination>span").eq(0).addClass("active");
                me.bannerMove(data.guangao.length)
                // console.log(html);
                // me.swiper();
            } else {
                console.log(data.error);
            }
        },
        error: function error(_error) {
            console.log("广告图接口", _error);
        }
    });
};

Index.prototype.bannerMove = function (length) {
    var index = 0;
    // // 点击上一张
    // $("a:first").click(function () {
    //     prev_pic();
    // })
    // // 点击下一张
    // $("a:last").click(function () {
    //     next_pic();
    // })


    // 悬浮停止
    $(".banner").mouseover(function () {
        clearInterval(id);
    });
    $(".banner").mouseout(function () {
        autoplay();
    })
    $(".banner>.pagination>span").click(function () {
        index = $(this).index();
        addStyle();
    })

    // 下一张
    function next_pic() {
        index++;
        if (index > length) {
            index = 0;
        }
        addStyle();
    }

    // 上一张
    function prev_pic() {
        index--;
        if (index < 0) {
            index = length;
        }
        addStyle();
    }

    // 控制图片显示隐藏,小圆点背景色
    function addStyle() {
        $(".banner>.container>a").eq(index).fadeIn();
        $(".banner>.container>a").eq(index).siblings().fadeOut();
        $(".banner>.pagination>span").eq(index).addClass("active");
        $(".banner>.pagination>span").eq(index).siblings().removeClass("active");
    }

    // 自动轮播
    var id;
    autoplay();
    function autoplay() {
        id = setInterval(function () {
            next_pic();
        }, 3500)
    }
};
// 日历
Index.prototype.calendar = function (data) {
    var sessions = [];
    // console.log(data);
    var html = "";
    var d = 0; //日期
    var nowTemp = new Date(); //当前时间
    var oneDayLong = 24 * 60 * 60 * 1000; //一天的毫秒数
    var c_time = nowTemp.getTime(); //当前时间的毫秒时间
    var c_day = nowTemp.getDay() || 7; //当前时间的星期几
    var m_time = c_time - (c_day - 1) * oneDayLong; //当前周一的毫秒时间
    var monday = new Date(m_time); //设置周一时间对象
    var m_date = monday.getDate(); //周一的日期

    var dt = new Date();
    var nextMonthFirstDay = new Date(dt.getFullYear(), dt.getMonth() + 1, 1); //下一个第一天
    var curMonthFirstDay = new Date(dt.getFullYear(), dt.getMonth(), 1); //这个月第一天
    var oneDay = 1000 * 60 * 60 * 24;
    var curLastTime = new Date(nextMonthFirstDay - oneDay);
    var prevLastTime = new Date(curMonthFirstDay - oneDay);
    var curLastDay = curLastTime.getDate(); //本月最后一天
    var prevLastDay = prevLastTime.getDate(); //上月最后一天

    $("#month").text(nowTemp.getMonth() + 1 + "月");
    // 本月还剩大于等于14天
    if (curLastDay - m_date >= 14) {
        for (var i = m_date; i < m_date + 14; i++) {
            var dayId = zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(i);
            d++;
            var session = 0;
            $.each(data, function (index, val) {
                if (val.gdate.substr(5, 5) == zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(i)) {
                    session++;
                }
            });
            // console.log(dt.getDate());
            if (session > 0 && i >= dt.getDate()) {
                html += "<a href=\"period-list.html?id=" + dayId + "\" class=\"" + (i == nowTemp.getDate() ? 'today' : 'active') + "\">" + i + " <span>" + chineseNum(session) + "<small>场</small></span></a> ";
            } else {
                html += "<em>" + i + "</em>";
            }
        }
    } else {
        for (var i = m_date; i <= prevLastDay; i++) {
            var dayId = zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(i);
            d++;
            var session = 0;
            $.each(data, function (index, val) {
                if (val.gdate.substr(5, 5) == zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(i)) {
                    session++;
                }
            });
            if (session > 0 && i >= dt.getDate()) {
                html += "<a href=\"period-list.html?id=" + dayId + "\" class=\"" + (i == nowTemp.getDate() ? 'today' : 'active') + "\">" + i + "<span>" + chineseNum(session) + "<small>场</small></span></a>";
            } else {
                html += "<em>" + i + "</em> ";
            }
        }
        for (var n = 1; n <= 14 - d; n++) {
            var dayId = zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(n);
            var session = 0;
            $.each(data, function (index, val) {
                if (val.gdate.substr(5, 5) == zeroDay(nowTemp.getMonth() + 1) + "-" + zeroDay(n)) {
                    session++;
                }
            });
            if (session > 0 && n >= dt.getDate()) {
                html += "<a href=\"period-list.html?id=" + dayId + "\" class=\"" + (n == nowTemp.getDate() ? 'today' : 'active') + "\">" + n + "<span>" + chineseNum(session) + "<small>场</small></span></a> ";
            } else {
                html += "<em>" + n + "</em>";
            }
        }
    }
    // console.log(html);
    $("#calendarDate").html(html);
};
// swiper轮播banner
Index.prototype.swiper = function () {
    var mySwiper1 = new Swiper('.swiper-container1', {
        loop: true,
        autoplay: 3000,
        pagination: '.pagination1',
        paginationClickable: true
    });
    var mySwiper2 = new Swiper('.swiper-container2', {
        loop: true,
        autoplay: 6000,
        // pagination: '.pagination2',
        paginationClickable: true
    });
};
// 专场隐藏菜单
Index.prototype.menu = function () {
    var me = this;
    var index = 0;
    $(".auction-list li a").hover(function () {
        // 德泉缘推广专场
        if ($(this).parent().attr('class') == 'tuiguang') {
            return false;
        }
        $(".auction-list li a").removeClass("active");
        $(this).addClass("active");
        $(".sessions-list").css("top", $(this).offset().top - 143 + "px");
        index = $(this).index();
        var MyHref = $(this).attr("href");
        var gIndex = MyHref.indexOf("=");
        var groupId = MyHref.substr(gIndex + 1, MyHref.length);
        me.dataList(groupId);
        // 详情显示出来
        $(".sessions-list").show();
        $(this).find(".arrow-t").show();
    }, function () {
        $(".arrow-t").hide();
        $(".sessions-list").hide();
    });

    $(".sessions-list").hover(function () {
        $(".auction-list li .active .arrow-t").show();
        $(this).show();
    }, function () {
        $(".arrow-t").hide();
        $(this).hide();
    });
};
// 图库
Index.prototype.map = function () {
    var map = [{
        "title": "秦汉"
    }, {
        "title": "三国两晋南北朝"
    }, {
        "title": "隋唐五代十国"
    }, {
        "title": "宋"
    }, {
        "title": "辽金西夏元"
    }, {
        "title": "明清"
    }, {
        "title": "邻国"
    }, {
        "title": "花钱"
    }, {
        "title": "钱范"
    }, {
        "title": "金银锭"
    }, {
        "title": "机制币"
    }, {
        "title": "纸币"
    }];
    var mapHtml = "";
    $.each(map, function (index, val) {
        mapHtml += "<li class=\"" + ((index + 1) % 4 == 0 ? 'short' : '') + "\">\n            <a href=\"map.html?stype=[" + escape(val.title) + "]\"><i class=\"iconfont\">&#xe6a3;</i>" + val.title + "</a>\n        </li>";
    });
    $("#mapBox").html(mapHtml);
};
// 折线图
Index.prototype.echart = function () {
    var myChart = echarts.init(document.getElementById('main'));
    var me = this;
    $.ajax({
        url: MyUrl + "/auctionGoods/getYearMovingAverage",
        type: "get",
        success: function success(data) {
            // console.log(data.data);
            if (data.code == 200) {
                var dateList = [];
                var valueList = [];
                var valueList2 = [];
                for (key in data.data) {
                    dateList.push(key);
                    valueList.push(data.data[key].MA15GQB);
                    valueList2.push(data.data[key].MA15JZB);
                }
                dateList = dateList.reverse();
                valueList = valueList.reverse();
                valueList2 = valueList2.reverse();
                option = {
                    tooltip: {
                        trigger: 'axis'
                    },
                    xAxis: {
                        data: dateList,
                        axisLabel: {
                            show: true,
                            textStyle: {
                                fontSize: 10 //更改坐标轴文字大小
                            }
                        }
                    },
                    grid: {
                        left: 0, // 调整这个属性
                        containLabel: true
                    },
                    yAxis: {
                        axisLabel: {
                            show: true,
                            interval: 0,
                            formatter: function formatter(value) {
                                if (value >= 10000) {
                                    value = value / 10000 + 'W';
                                }
                                if (value >= 1000) {
                                    value = value / 1000 + 'K';
                                }
                                return value;
                            },
                            textStyle: {
                                color: '#a1c6fd', //更改坐标轴文字颜色
                                fontSize: 10 //更改坐标轴文字大小
                            }
                        }
                    },
                    series: [{
                        name: '古钱币',
                        type: 'line',
                        showSymbol: false,
                        data: valueList,
                        itemStyle: {
                            normal: {
                                color: '#C1232B',
                                lineStyle: {
                                    width: 1 // 0.1的线条是非常细的了
                                }
                            }
                        }
                    }, {
                        name: '机制币',
                        type: 'line',
                        showSymbol: false,
                        data: valueList2,
                        itemStyle: {
                            normal: {
                                color: '#5470C6',
                                lineStyle: {
                                    width: 1 // 0.1的线条是非常细的了
                                }
                            }
                        }
                    }]
                };
                // 使用刚指定的配置项和数据显示图表。
                myChart.setOption(option);
            } else {
                console.log(data.msg);
            }
        },
        error: function error(_error2) {
            console.log("成交单价指数接口", _error2);
        }
    });
};
// 获取cid
Index.prototype.getCid = function () {
    var me = this;
    $.ajax({
        url: Url + "/v3/auth/cid.jsp?jscall=?",
        type: "post",
        data: {
            "app": "H5",
            "v": "1.0.0"
        },
        dataType: "jsonp",
        contentType: 'application/x-www-form-urlencoded',
        success: function success(data) {
            if (data.error == "0") {
                setCookie("cid", data.cid);
                if (Mid) {
                    clearCookie("mid");
                }
                console.log("重新保存Cid：" + getCookie("cid"));
                location.reload();
            } else {
                console.log(data.error);
            }
        },
        error: function error(_error) {
            console.log("获取cid接口", _error);
        }
    });
};
// 聊天室提示
Index.prototype.chartroomUpdate = function () {
    var me = this;
    var i = 0;
    $.ajax({
        url: "https://la-info.huaxiaguquan.com/l.jsp?jscallback=?",
        type: "post",
        async: false,
        dataType: "jsonp",
        jsonpCallback: "update",
        success: function (data) {
            console.log(data);
            if (data.cmd != "none") {
                $("#chatRoomTip").show();
                $("#chartroomBtn").show();
                // 开启10s刷新价格的实时更新
                var contentHtml = '<div class="chat-price"> <p>' + AuctionGroupName + '</p></div>';
                if (data.cmd == 'actn_price' || data.cmd == 'actn_start') {
                    if (!me.TimeOver) {
                        // contentHtml=`<img src="${AliUrl+"/pic/"+me.getItemPic(data.gid)}" alt="">
                        // <div class="chat-price">
                        //     <p>${me.getItemName(data.gid)}</p>
                        //     <span>当前价 <em>¥${data.price||0}</em> 元 </span>
                        // </div>`
                        contentHtml = "<img src=\"" + (AliUrl + "/pic/" + me.getItemPic(data.gid)) + "\" alt=\"\">\n                    <div class=\"chat-price\">\n                        <p>" + me.getItemName(data.gid) + "</p>\n                        <span>当前价 <em>¥" + (data.price || 0) + "</em> 元 </span>\n                    </div>";
                    } else {
                        contentHtml = '<div class="chat-price"> <p>实时播报已暂停，拍卖进行中…</p></div>';
                    }
                    if (me.chartroomUpdateFlg) {
                        me.chartroomUpdateFlg = false;
                        me.Timer = setInterval(function () {
                            i++;
                            // 聊天室实时更新
                            me.chartroomUpdate();
                            if (i >= 60) {
                                // console.log(1111);
                                me.TimeOver = true;
                                clearInterval(me.Timer);
                            }
                        }, 1000)
                    }
                } else if (data.cmd == 'wait') {
                    contentHtml = '<div class="chat-price"> <p>' + AuctionGroupName + '</p></div>';
                }
                var html = '<div class="center">' +
                    '<div class="chat-l">' +
                    '<a href="chatroom-list.html?groupid=' + me.GroupId + '"> 聊天室<br>浏览预展</a>' +
                    '</div>' +
                    '<div class="chat-m">' +
                    contentHtml +
                    '</div>' +
                    '<div class="chat-r">' +
                    '<a href="jump-chatroom.html" class="btn">进入聊天室竞买 <i class="iconfont">&#xe73d;</i></a>' +
                    '<a href="javascript:;" class="iconfont close">&#xe6f3;</a>' +
                    '</div>' +
                    '</div>';
                $("#chatRoomTip").html(html);
            } else {
                clearInterval(me.Timer);
                $("#chatRoomTip").hide();
            }
        }
    })
}

// 聊天室
Index.prototype.getChatRoom = function () {
    // var imgs = [];
    // 计算图片的宽度（为了滚动插件正常，必须设置宽度）
    // for(var i=0;i<10;i++){
    //     imgs[i]=new Image();
    //     imgs[i].src = document.getElementsByClassName("chatImg" + i)[0].src;
    //     (function(i){
    //         imgs[i].onload=function(){
    //             var heightScale = this.height / 140;
    //             var imgWidth = this.width / heightScale + "px";
    //             $(".chatImg"+i).css("width",imgWidth);
    //         }
    //     }(i))

    // }
    // setTimeout(function () {
    //     $("#roll").scrollForever();
    // }, 500);
    $("#chatRoomTip").hide();
    $("#chartroomBtn").hide();
    var me = this;
    $.ajax({
        url: Url + "/v3/live/index.jsp?jscall=?",
        type: "post",
        data: {
            "cid": getCookie("cid")
        },
        dataType: "jsonp",
        success: function success(data) {
            // console.log('聊天室：',data);
            if (!data.cid) {
                // 获取cid
                me.getCid();
            }
            if (data.error == "0") {
                me.Mid = data.mid;
                var item = data.grouplist[0];
                // var item2 = data.grouplist[1];
                me.GroupId = item.groupid;
                sessionStorage.setItem("chatroomId", item.groupid);
                $("#groupName").html(item.groupname);
                var html = "";
                $.each(item.pics, function (index, val) {
                    html += "<li><a href=\"chatroom-list.html?groupid=" + item.groupid + "\"><span><img class=\"chatImg chatImg" + index + "\" src=\"" + AliUrl + "/pic/" + smallImg(val) + "\" alt=\"\"></span> </a></li>";
                });
                // $.each(item2.pics, function (index, val) {
                //     html += "<li><a href=\"chatroom-list.html?groupid=" + item2.groupid + "\"><span><img class=\"chatImg chatImg" + index + "\" src=\"" + AliUrl + "/pic/" + smallImg(val) + "\" alt=\"\"></span> </a></li>";
                // });
                $("#chatPic").html(html);

                var new_image = new Image();
                // 计算图片的宽度（为了滚动插件正常，必须设置宽度）
                $.each(item.pics, function (index, val) {
                    setTimeout(function () {
                        new_image.src = document.getElementsByClassName("chatImg" + index)[0].src;
                        var heightScale = new_image.height / 140;
                        var imgWidth = new_image.width / heightScale + "px";
                        $(".chatImg" + index).css("width", imgWidth);
                    }, 200);
                });
                setTimeout(function () {
                    $("#groupName span").scrollForever();
                    $("#roll").scrollForever();
                }, 500);
            } else {
                if (data.error.substr(0, 5) == "-1000") {
                    me.Tip = "访问频率超限，稍后再试";
                    // me.SafePopup=true;
                } else {
                    me.Tip = data.error;
                }
            }
        },
        error: function error(_error3) {
            console.log("聊天室接口", _error3);
        }
    });

    // $.ajax({
    //     url: "js/json/chartRoom3.json",
    //     type: "get",
    //     success: function success(data) {
    //         console.log(data.jizhibi);
    //         var html = "";
    //         $.each(data.jizhibi, function (index, val) {
    //             html += "<li><a href=\"chatroom-list2.html\"><span><img class=\"big-img chatImg" + index + "\" src=\""+AliUrl+"/pic/yihe/images_data_jiade/" + val[2][0] + "\" alt=\"\"></span> </a></li>";
    //         });
    //         $("#chatPic").html(html);

    //         var new_image = new Image();
    //         // 计算图片的宽度（为了滚动插件正常，必须设置宽度）
    //         $.each(data.jizhibi, function (index, val) {
    //             new_image.src = document.getElementsByClassName("chatImg" + index)[0].src;
    //             var heightScale = new_image.height / 140;
    //             var imgWidth = new_image.width / heightScale + "px";
    //             $(".chatImg").css("width",imgWidth);
    //         });
    //         // 聊天室无限滚动图片
    //         // $('#roll').liMarquee({
    //         //     scrollamount: 30,
    //         //     direction: 'left'
    //         // });
    //         setTimeout(function () {
    //             $("#roll").scrollForever();
    //         }, 300);
    //     },
    //     error: function error(_error3) {
    //         console.log("聊天室接口", _error3);
    //     }
    // });
};
// 专场列表
Index.prototype.getAuctionField = function () {
    var me = this;
    $.ajax({
        url: Url + "/v3/xpai/list.jsp?jscall=?",
        type: "post",
        data: {
            "cid": getCookie("cid")
        },
        dataType: "jsonp",
        success: function success(data) {
            // console.log(data);
            if (data.error == "0") {
                // 日历
                // me.calendar(data.grouplist);
                // 置顶特殊场次
                $.each(data.grouplist, function (index, val) {
                    $.each(data.topid, function (i1, v2) {
                        if (val.groupId == v2) {
                            val.refine = true;
                            data.grouplist.unshift(data.grouplist.splice(index, 1)[0])
                        }
                    })
                })
                me.Mid = data.mid;
                var html = "<div class=\"yesterday\"><a href='javascript:;'><em><small>已 结 束</small></em><span>最近已结标专场</span><i class=\"arrow-t\"></i></a></div>";
                // html += "<li class='tuiguang'><a href='https://mhx.huaxiaguquan.com/chatroom-list-custom.html?rrid=4277'><em>※</em><u><span>德泉缘2025上海之巅春季拍卖会</span><span>05-11 (周日) 10:00</span><span><big>785</big>件藏品</span></u><i class='arrow-t'></i></a></li>"
                var date = new Date();
                var listIndex = 1; //列表数量
                $.each(data.grouplist, function (index, val) {
                    var todayDate = date.getFullYear() + "-" + (date.getMonth() < 9 ? '0' : '') + (date.getMonth() + 1) + "-";
                    todayDate += (date.getDate() < 10 ? '0' : '') + date.getDate();
                    if (val.gdate.substr(0, 10) >= todayDate) {
                        listIndex++;
                        val.today = today(val.gdate);
                        html += "<li class=\"" + (val.today ? 'today' : '') + " " + (val.refine ? 'refine' : '') + "\" date=\"" + val.gdate.substr(5, 5) + "\">\n                            <a href=\"goods-list.html?gid=" + val.groupId + "\">\n                                <em>" + (val.refine ? '精品推荐' : listIndex - 1) + "</em>\n                                <u>\n                                    <span>" + val.groupName + "</span>\n                                    <span>" + getWeek(val.gdate) + " </span>\n                                    <span><big>" + val.countx + "</big>件藏品</span>\n                                </u>\n                                <i class=\"arrow-t\"></i>\n                            </a>\n                        </li>";
                    }
                });
                // 余数：(listIndex+1)%6
                var addCount = Math.ceil(listIndex / 6) * 6;
                var addIndex = listIndex;
                for (var i = listIndex; i < addCount; i++) {
                    if (data.grouplist.length > i) {
                        addIndex++;
                        var val = data.grouplist[i];
                        html += "<li class=\"end-day " + (val.today ? 'today' : '') + "\" date=\"" + val.gdate.substr(5, 5) + "\">\n                            <a href=\"goods-list.html?gid=" + val.groupId + "\">\n                                <em>" + (addIndex - 1) + "</em>\n                                <u>\n                                    <span>" + val.groupName + "</span>\n                                    <span>" + getWeek(val.gdate) + " </span>\n                                    <span>" + val.countx + "件藏品</span>\n                                </u>\n                                <i class=\"arrow-t\"></i>\n                            </a>\n                        </li>";
                    }
                }

                $('#auctionFieldBox').html(html);
                $("#calendarDate a").hover(function () {
                    var MyHref = $(this).attr("href");
                    var gIndex = MyHref.indexOf("=");
                    var date = MyHref.substr(gIndex + 1, MyHref.length);
                    $(".auction-list li[date=" + date + "]").addClass("choose");
                }, function () {
                    $(".auction-list li").removeClass("choose");
                });
                // 暂时取消权限限制
                // me.permission();
                // 默认有访问权限
                me.menu();
                $("#auctionFieldBox").removeClass('no-permission')

                $(".yesterday").on('click', 'a', function () {
                    if (!Mid) {
                        location.href = "login.html"
                    } else {
                        location.href = "period-list.html?id=end"
                    }
                })
                //-------
            } else {
                me.Tip = data.error;
                if (data.error.includes("-1011")) {
                    console.log(data.error);
                    me.getCid();
                }
            }
        },
        error: function error(_error4) {
            console.log("专场列表接口", _error4);
        }
    });
};
// 获取专场数据
Index.prototype.dataList = function (groupid) {
    var me = this;
    $.ajax({
        url: Url + "/v3/xpai/group.jsp?jscall=?",
        type: "post",
        data: {
            "cid": getCookie("cid"),
            gid: groupid,
            pid: 1,
            gtype: "",
            order: 20
        },
        dataType: "jsonp",
        success: function success(data) {
            // console.log(data);
            if (data.error == "0") {
                $('#auctionName').html("<a href=\"goods-list.html?gid=" + groupid + "\"> " + data.gname + " <i class=\"iconfont\">&#xe68c;</i></a>");
                $('#auctionTime').html(getWeek(data.gdate) + " 结标 <em>共" + data.gtotal + "件</em>");
                var html = "";
                $.each(data.items, function (index, val) {
                    if (index < 9) {
                        html += "<li>\n                            <a  target=\"_blank\" href=\"goods-detail.html?id=" + val.itemcode + "\" class=\"img-box\">\n                                <span><img class=\"goods lazy\" data-original=\"" + AliUrl + "/pic/" + smallImg(val.pic) + "\" alt=\"\"></span>\n                            </a>\n                            <p><a  target=\"_blank\" href=\"goods-detail.html?id=" + val.itemcode + "\">" + val.itemname + "</a></p>\n                            <em><a  target=\"_blank\" href=\"goods-detail.html?id=" + val.itemcode + "\"><small>¥</small>" + addCommas(val.itemcprice) + "</a></em>\n                        </li>";
                    }
                });
                $('#auctionList').html(html);

                // 图片懒加载
                $("img.lazy").lazyload({
                    placeholder: AliUrl + "/app/v3/images/icon/load-img.gif", //用图片提前占位
                    effect: "fadeIn"
                });

                // ie6下自适应图片宽高
                setTimeout(function () {
                    if ($.browser.msie && ($.browser.version == '6.0' || $.browser.version == '7.0') && !$.support.style) {
                        console.log("ie6下计算图片尺寸，共：", $(".goods").length + "张图片");
                        for (var i = 0; i < $(".goods").length; i++) {
                            var w = $(".goods")[i].width;
                            var h = $(".goods")[i].height;
                            if (w > h) {
                                $(".goods")[i].width = 140;
                            } else {
                                $(".goods")[i].height = 140;
                            }
                        }
                    }
                }, 200);
            } else {
                me.Tip = data.error;
            }
        },
        error: function error(_error5) {
            console.log("专场详情接口", _error5);
        }
    });
};
Index.prototype.alert = function () {
    var lastDate = window.localStorage.getItem('lastDate');
    var today = new Date();
    if (today.getDate() != parseInt(lastDate)) {
        $('.onceShow').show();
        $('.onceShow button').on('click', function () {
            $('.onceShow').hide();
        })
        window.localStorage.setItem('lastDate', today.getDate().toString());
    }
};
// 猜你喜欢，精品推荐
Index.prototype.getYoulike = function () {
    var me = this;
    // 拍品推荐的标签参数 读取本地缓存
    if (me.BaseLabel) {
        console.log("本地缓存的推荐标签", me.BaseLabel);
        me.likeList();
    } else {
        $.ajax({
            url: qgUrl + "/userVifLabel/getUserBaseLabel",
            type: "get",
            data: {
                "cid": getCookie("cid")
            },
            // dataType: "jsonp",
            success: function success(data) {
                // console.log(data);
                if (data.code == 200) {
                    if (data.data.userRecommend == "") {
                        me.BaseLabel = data.data.userBase;
                    } else {
                        me.BaseLabel = data.data.userBase + "," + data.data.userRecommend;
                    }
                    setCookie("baseLabel", me.BaseLabel);
                    console.log("接口中的推荐标签", me.BaseLabel);
                } else {
                    me.BaseLabel = "240,60,70,40,50";
                    Toast(data.error);
                    console.log(data.error);
                }
                me.likeList();
            },
            error: function error(_error6) {
                console.log(_error6);
            }
        });
    }
};
Index.prototype.likeList = function () {
    var me = this;
    $.ajax({
        url: qgUrl + "/priceSearch/solrHomeRecommend",
        type: "get",
        data: {
            "baseLabel": me.BaseLabel,
            "pageNum": 1
        },
        // dataType: "jsonp",
        success: function success(data) {
            if (data.code == "200") {
                console.log(data);
                // Cid = data.cid;
                $.each(data.data, function (index, val) {
                    var videoIcon = '<i class="iconfont icon-video ' + (val.GMEDIA ? '' : 'hide') + '">&#xe6ed;</i>';
                    me.KanKanHtml += "<li>\n                        <div class=\"goods-img\">\n                            <a  target=\"_blank\" href=\"goods-detail.html?id=" + val.GID + "&recommend=1 \" class=\"img-box\">" + videoIcon + "<span><img class=\"big-img\" data-original=\"" + AliUrl + "/pic/" + smallImg(val.GPIC) + "\" alt=\"\"></span>\n                            </a>\n                        </div>\n                        <h3> \n                            <a  target=\"_blank\" href=\"goods-detail.html?id=" + val.GID + "&recommend=1\">\n                                <!-- <i class=\"fire\"></i> -->\n                                " + val.GNAME + "\n                            </a>\n                        </h3>\n                        <p>\n                            <a  target=\"_blank\" href=\"goods-detail.html?id=" + val.GID + "&recommend=1\">\n                                <span>结标时间：" + val.GDATE.replace(/\//g, "-").substr(5) + "</span>\n                                <em><small>¥</small>" + addCommas(val.GPRICE) + "</em>\n                            </a>\n                            \n                        </p>\n                    </li>";
                    // <a href="javascript:;" class="zan">
                    //     <i class="iconfont ${index==0?'active':''}">${index==0?"&#xe6d1;":"&#xe662;"}</i>
                    //     <span> 2.1k</span>
                    // </a>
                });
                $("#hotListBox").html(me.KanKanHtml);
                $(".big-img").lazyload({
                    placeholder: AliUrl + "/app/v3/images/icon/load-img.gif", //用图片提前占位
                    effect: "fadeIn", // 载入使用何种效果
                    event: "sporty"
                });
                $(".big-img").trigger("sporty");
            }
        },
        error: function error(_error7) {
            console.log("猜你喜欢接口", _error7);
        }
    });
};
Index.prototype.permission = function () {
    var me = this;
    $.ajax({
        type: 'post',
        url: Url + "/v3/auth/xpai.jsp?jscall=?",
        contentType: 'application/json',
        dataType: 'jsonp',
        data: {
            cid: getCookie("cid")
        },
        success: function (res) {
            if (res.error == "0") {
                if (res.tmauctionview == "true") {
                    me.menu();
                    //有权限删除模糊
                    $("#auctionFieldBox").removeClass('no-permission')
                }
            }
        }
    })
};
// 新闻
Index.prototype.news = function () {
    jQuery.support.cors = true;
    $.ajax({
        url: ysUrlNew + "/news/news-info/list",
        type: "post",
        data: {
            "state": 0,
            "curPage": 1,
            "pageSize": 6
        },
        async: false,
        success: function success(data) {
            // console.log(data);
            var html = "";
            $.each(data.data.records, function (index, val) {
                var type = "";
                // if (val.belongId == 0) {
                //     type = "慈善助学";
                // } else if (val.belongId == 1) {
                //     type = "活动资讯";
                // } else if (val.belongId == 2) {
                //     type = "展会播报";
                // } else if (val.belongId == 3) {
                //     type = "原创文章";
                // } else if (val.belongId == 4) {
                //     type = "华夏评级";
                // } else {
                //     type = "其它分类";
                // }
                html += "<li>\n                    <a href=\"news-detail.html?newsid=" + val.newsId + "\">[" + val.UpdateTime.substr(5, 5).replace(/\//, ".") + "] " + val.title + " </a>\n                </li>";
            });
            $("#newsBox").html(html);
        },
        error: function error(_error8) {
            console.log("新闻接口", _error8);
        }
    });
};
window.index = new Index();
index.init();