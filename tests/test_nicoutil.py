#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

import nicoutil


def test_basic():
    test_string = """\
　あるところに、牛を持っている百姓がありました。その牛は、もう年をとっていました。長い年の間、その百姓のために重い荷をつけて働いたのであります。そして、いまでも、なお働いていたのであったけれど、なんにしても、年をとってしまっては、ちょうど人間と同じように、若い時分ほど働くことはできなかったのです。
　この無理もないことを、百姓はあわれとは思いませんでした。そして、いままで自分たちのために働いてくれた牛を、大事にしてやろうとは思わなかったのであります。
「こんな役にたたないやつは、早く、どこかへやってしまって、若いじょうぶな牛と換えよう。」と思いました。
　秋の収穫もすんでしまうと、来年の春まで、地面は、雪や、霜のために堅く凍ってしまいますので、牛を小舎の中に入れておいて、休ましてやらなければなりません。この百姓は、せめて牛をそうして、春まで休ませてやろうともせずに、
「冬の間こんな役にたたないやつを、食べさしておくのはむだな話だ。」といって、たとえ、ものこそいわないけれど、なんでもよく人間の感情はわかるものを、このおとなしい牛をひどいめにあわせたのであります。
　ある、うす寒い日のこと、百姓は、話に、馬の市が四里ばかり離れた、小さな町で開かれたということを聞いたので、喜んで、小舎の中から、年とった牛を引き出して、若い牛と交換してくるために町へと出かけたのでした。
　百姓は、自分たちといっしょに苦労をした、この年をとった牛に分かれるのを、格別悲しいとも感じなかったのであるが、牛は、さもこの家から離れてゆくのが悲しそうに見えて、なんとなく、歩く足つきも鈍かったのでありました。
"""  # noqa
    check(test_string)


def test_basic2():
    test_string = """\
　あるところに、牛を持っている百姓がありました。その牛は、もう年をとっていました。長い年の間、その百姓のために重い荷をつけて働いたのであります。そして、いまでも、なお働いていたのであったけれど、なんにしても、年をとってしまっては、@abcdちょうど人間と同じように、若い時分ほど働くことはできなかったのです。
　この無理もないことを、百姓はあわれとは思いませんでした。そして、いままで自分たちのために働いてくれた牛を、大事にしてやろうとは思わなかったのでhttp://example.comあります。
「こんな役にたたないやつは、早く、どこかへやってしまって、若いじょうぶな牛と換えよう。」と思いました。
　秋の収穫もすんでしまうと、来年の春まで、地面は、雪や、霜のために堅く凍ってしまいますので、https://example.co.jp/aaaaaaaaaa/aaaaaaaaaa/aaaaaaaaaa牛を小舎の中に入れておいて、休ましてやらなければなりません。この百姓は、せめて牛をそうして、aa春まで休ませてやろうともせずに、
「http://example.com/bbbbbbbbbb/bbbbbbbbbb冬の間こんな役にたたないやつを、食べさしておくのはむだな話だ。」といって、たとえ、ものこそいわないけれど、なんでもよく人間の感情はわかるものを、このおとなしい牛をひどいめにあわせたのであります。
　ある、うす寒い日のこと、百姓は、話に、馬の市が四里ばかり離れた、小さな町で開かれたということを聞いたので、喜んで、小舎の中から、年とった牛を引き出して、若い牛と交換してくるために町へと出かけたのでした。
　百姓は、自分たちといっしょに苦労をした、この年をとった牛に分かれるのを、格別悲しいとも感じなかったのであるが、牛は、さもこの家から離れてゆくのが悲しそうに見えて、なんとなく、歩く足つきも鈍かったのでありました。
"""  # noqa
    check(test_string)


def test_short():
    test_string = """\
　あるところに、牛を持っている百姓がありました。その牛は、もう年をとっていました。長い年の間、その百姓のために重い荷をつけて働いたのであります。そして、いまでも、なお働いていたのであったけれど、なんにしても、
"""  # noqa
    check(test_string)


def test_http():
    test_string = """\
　あるところに、牛を持っている百姓がありました。その牛は、もう年をとっていました。長い年の間、その百姓のために重い荷をつけて働いたのであります。そして、いまでも、なお働いていたのであった。
http://www.chikuwachan.com/live/catalog/index.cgi?category=&sort=room2&rev=co10000
"""  # noqa
    check(test_string)


def test_nico():
    test_string = """\
abc
>>sm123
sm123
>>lv123
lv123
>>im123
im123
>>co123
co123
abc
"""  # noqa
    check(test_string)


def test_mail_twitter():
    test_string = """\
あるhttp://example.com/aaaaaaaaa/bbbbbbbbbbところに、test@example.comを持っている百姓が@testありました。
"""  # noqa
    check(test_string)


def test_google():
    test_string = """\
谷津駅-習志野市コンビニ 2.6km [goo.gl/JGdbXl]\n0102 さっき倒れていた、ダメットがしばらくパソコンを預かる。\n　　 コメントに反応できているのでまだ余裕はありそう。\n 　　 裏では西岡が配信をとっている様子でしゃべりまくっている。\n0105 全裸待機中、リア凸。タウリン3000mgをケースで差し入れ。\n　　 XL一枚購入。\n　　 サイコロ「5」緑「5000円ですー。」\n　　 全裸待機中、暗黒札をもらって「つかいますー。」\n　　 リスナー、リア凸。リポビタンD二本を差し入れ。\n　　 よっさんに、なけなしの1000円を差し入れ。\n　　 10秒以内によっさんのBSPを打ってくれたらもらうことに。\n　　 ぎりぎり10秒ではまにあわず。よさんBSP「かな 」\n    \n(省略しています。全て読むにはこのリンクをクリック！)
"""  # noqa
    check(test_string)


def check(target):
    # need to convert body from str type to unicode type
    target = target.decode('UTF-8')
    print type(target)

    statuses = nicoutil.create_twitter_statuses(
        u"(ななしのよっしん)\n", u"[続き] ", target, u" [続く]")

    index = 0
    for status in statuses:
        print u"*** index: %d length: %d status: [%s]\n" % (index, len(status), status)

        # adjust length of url string always be 23 bytes
        status = re.sub(nicoutil.REGEXP_HTTP, '12345678901234567890123', status)
        status = re.sub(nicoutil.REGEXP_GOOGLE, '12345678901234567890123', status)

        assert len(status) <= 140
        index += 1


def test_replace_atmark():
    statuses = nicoutil.create_twitter_statuses(u"a", u"", u"@abc", u"")
    assert statuses[0] == u"a%abc"

    statuses = nicoutil.create_twitter_statuses(u"a", u"", u"＠abc", u"")
    assert statuses[0] == u"a%abc"
