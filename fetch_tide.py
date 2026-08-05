#!/usr/bin/env python3
"""
気象庁の潮位表テキストデータを取得し、港ごとのJSONファイルに変換する。

フォーマット仕様（気象庁公式）:
    1-72 カラム  : 毎時潮位（3桁×24時間）cm
    73-78 カラム : 年月日（YYMMDD）
    79-80 カラム : 地点記号（2桁）
    81-108 カラム: 満潮時刻・潮位（時刻4桁 + 潮位3桁）× 4回
    109-136 カラム: 干潮時刻・潮位（時刻4桁 + 潮位3桁）× 4回
    欠測: 時刻=9999, 潮位=999

出力: data/tide/{YYYY}/{CODE}.json
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# 対象港リスト（気象庁 潮位表掲載地点 全241港）
# build_ports.py で JMA suisan ページから自動生成（lat/lon は度分→十進度）
PORTS = [
    {"code": "A0", "name": "紋別", "lat": 44.35, "lon": 143.3667},
    {"code": "A1", "name": "弟子待", "lat": 33.9333, "lon": 130.9333},
    {"code": "A3", "name": "森", "lat": 42.1167, "lon": 140.6},
    {"code": "A5", "name": "松前", "lat": 41.4167, "lon": 140.1},
    {"code": "A6", "name": "羅臼", "lat": 44.0167, "lon": 145.2},
    {"code": "A8", "name": "室蘭", "lat": 42.35, "lon": 140.95},
    {"code": "A9", "name": "浦河", "lat": 42.1667, "lon": 142.7667},
    {"code": "AB", "name": "油津", "lat": 31.5833, "lon": 131.4167},
    {"code": "AH", "name": "青浜", "lat": 33.95, "lon": 131.0167},
    {"code": "AK", "name": "明石", "lat": 34.65, "lon": 134.9833},
    {"code": "AM", "name": "尼崎", "lat": 34.7, "lon": 135.4},
    {"code": "AO", "name": "青森", "lat": 40.8333, "lon": 140.7667},
    {"code": "AS", "name": "網走", "lat": 44.0167, "lon": 144.2833},
    {"code": "AW", "name": "阿波由岐", "lat": 33.7667, "lon": 134.6},
    {"code": "AX", "name": "青木", "lat": 34.3667, "lon": 133.6833},
    {"code": "AY", "name": "鮎川", "lat": 38.3, "lon": 141.5},
    {"code": "B1", "name": "十勝", "lat": 42.3, "lon": 143.3167},
    {"code": "B2", "name": "留萌", "lat": 43.95, "lon": 141.6333},
    {"code": "B3", "name": "小樽", "lat": 43.2, "lon": 141.0},
    {"code": "B4", "name": "大間", "lat": 41.5333, "lon": 140.9},
    {"code": "B5", "name": "岩内", "lat": 42.9833, "lon": 140.5},
    {"code": "B6", "name": "寿都", "lat": 42.8, "lon": 140.2333},
    {"code": "BP", "name": "別府", "lat": 33.3, "lon": 131.5},
    {"code": "C8", "name": "苫小牧東", "lat": 42.6, "lon": 141.8167},
    {"code": "CB", "name": "千葉港", "lat": 35.6, "lon": 140.1},
    {"code": "CC", "name": "父島", "lat": 27.1, "lon": 142.2},
    {"code": "CF", "name": "長府", "lat": 34.0167, "lon": 131.0},
    {"code": "CS", "name": "銚子漁港", "lat": 35.75, "lon": 140.8667},
    {"code": "D1", "name": "日立", "lat": 36.5, "lon": 140.6333},
    {"code": "D2", "name": "鹿島", "lat": 35.9333, "lon": 140.7},
    {"code": "D3", "name": "大洗", "lat": 36.3, "lon": 140.5667},
    {"code": "D4", "name": "八丈島（八重根）", "lat": 33.1, "lon": 139.7667},
    {"code": "D6", "name": "下田", "lat": 34.6833, "lon": 138.9667},
    {"code": "D8", "name": "湘南港", "lat": 35.3, "lon": 139.4833},
    {"code": "DJ", "name": "南大東", "lat": 25.8667, "lon": 131.2333},
    {"code": "DS", "name": "下関", "lat": 33.9333, "lon": 130.9333},
    {"code": "E6", "name": "石巻", "lat": 38.4, "lon": 141.2667},
    {"code": "EI", "name": "江井", "lat": 34.4667, "lon": 134.8333},
    {"code": "ES", "name": "江差", "lat": 41.8667, "lon": 140.1333},
    {"code": "F3", "name": "沓形", "lat": 45.1833, "lon": 141.1333},
    {"code": "FE", "name": "福江", "lat": 32.7, "lon": 128.85},
    {"code": "FK", "name": "深浦", "lat": 40.65, "lon": 139.9333},
    {"code": "G3", "name": "四日市港", "lat": 34.9667, "lon": 136.6333},
    {"code": "G4", "name": "三河", "lat": 34.7333, "lon": 137.3167},
    {"code": "G5", "name": "形原", "lat": 34.7833, "lon": 137.1833},
    {"code": "G8", "name": "衣浦", "lat": 34.8833, "lon": 136.95},
    {"code": "G9", "name": "石廊崎", "lat": 34.6167, "lon": 138.85},
    {"code": "GB", "name": "御坊", "lat": 33.85, "lon": 135.1667},
    {"code": "H1", "name": "下津", "lat": 34.1167, "lon": 135.1333},
    {"code": "HA", "name": "浜田", "lat": 34.9, "lon": 132.0667},
    {"code": "HC", "name": "八戸", "lat": 40.5333, "lon": 141.5333},
    {"code": "HG", "name": "八戸港", "lat": 40.5333, "lon": 141.55},
    {"code": "HK", "name": "函館", "lat": 41.7833, "lon": 140.7167},
    {"code": "HM", "name": "本牧", "lat": 35.4333, "lon": 139.6667},
    {"code": "HN", "name": "花咲", "lat": 43.2833, "lon": 145.5667},
    {"code": "HR", "name": "南風泊", "lat": 33.95, "lon": 130.8833},
    {"code": "HS", "name": "本渡瀬戸", "lat": 32.4333, "lon": 130.2167},
    {"code": "HW", "name": "日和佐", "lat": 33.7167, "lon": 134.55},
    {"code": "I4", "name": "赤羽根", "lat": 34.6, "lon": 137.1833},
    {"code": "I5", "name": "新潟東港", "lat": 37.9833, "lon": 139.2167},
    {"code": "I7", "name": "生地", "lat": 36.8833, "lon": 137.4167},
    {"code": "IJ", "name": "西表", "lat": 24.35, "lon": 123.75},
    {"code": "IK", "name": "石狩新港", "lat": 43.2167, "lon": 141.3},
    {"code": "IO", "name": "泉大津", "lat": 34.5167, "lon": 135.4},
    {"code": "IS", "name": "石垣", "lat": 24.3333, "lon": 124.1667},
    {"code": "IZ", "name": "糸崎", "lat": 34.4, "lon": 133.0833},
    {"code": "J2", "name": "岸和田", "lat": 34.4667, "lon": 135.3667},
    {"code": "J5", "name": "西宮", "lat": 34.7167, "lon": 135.3333},
    {"code": "J6", "name": "橘", "lat": 33.8667, "lon": 134.6333},
    {"code": "J8", "name": "与島", "lat": 34.3833, "lon": 133.8167},
    {"code": "J9", "name": "三田尻", "lat": 34.0333, "lon": 131.5833},
    {"code": "K1", "name": "姫路（飾磨）", "lat": 34.7833, "lon": 134.6667},
    {"code": "K5", "name": "萩", "lat": 34.4333, "lon": 131.4167},
    {"code": "KA", "name": "唐津", "lat": 33.4667, "lon": 129.9667},
    {"code": "KB", "name": "神戸", "lat": 34.6833, "lon": 135.1833},
    {"code": "KC", "name": "高知", "lat": 33.5, "lon": 133.5667},
    {"code": "KE", "name": "枝幸", "lat": 44.9333, "lon": 142.5833},
    {"code": "KG", "name": "鹿児島", "lat": 31.6, "lon": 130.5667},
    {"code": "KK", "name": "関空島", "lat": 34.4333, "lon": 135.2},
    {"code": "KM", "name": "小松島", "lat": 34.0167, "lon": 134.5833},
    {"code": "KN", "name": "熊野", "lat": 33.9333, "lon": 136.1667},
    {"code": "KO", "name": "皇后", "lat": 32.7167, "lon": 129.8333},
    {"code": "KP", "name": "霧多布", "lat": 43.0833, "lon": 145.1167},
    {"code": "KR", "name": "釧路", "lat": 42.9833, "lon": 144.3667},
    {"code": "KS", "name": "串本", "lat": 33.4833, "lon": 135.7667},
    {"code": "KT", "name": "口之津", "lat": 32.6, "lon": 130.2},
    {"code": "KU", "name": "熊本", "lat": 32.75, "lon": 130.5667},
    {"code": "KW", "name": "川崎", "lat": 35.5167, "lon": 139.75},
    {"code": "KZ", "name": "木更津", "lat": 35.3667, "lon": 139.9167},
    {"code": "L0", "name": "今治", "lat": 34.0667, "lon": 133.0},
    {"code": "L6", "name": "高知下田", "lat": 32.9333, "lon": 133.0},
    {"code": "L7", "name": "甲浦", "lat": 33.55, "lon": 134.3},
    {"code": "L8", "name": "伊予三島", "lat": 33.9833, "lon": 133.55},
    {"code": "LG", "name": "乙島", "lat": 34.5, "lon": 133.6833},
    {"code": "M0", "name": "今治市小島", "lat": 34.1333, "lon": 132.9833},
    {"code": "M1", "name": "来島航路", "lat": 34.1167, "lon": 132.9833},
    {"code": "M3", "name": "波止浜", "lat": 34.1, "lon": 132.9333},
    {"code": "MC", "name": "南鳥島", "lat": 24.2833, "lon": 153.9833},
    {"code": "MG", "name": "宮崎", "lat": 31.9, "lon": 131.45},
    {"code": "MI", "name": "舞阪", "lat": 34.6833, "lon": 137.6167},
    {"code": "MJ", "name": "三宅島(坪田)", "lat": 34.05, "lon": 139.55},
    {"code": "MK", "name": "枕崎", "lat": 31.2667, "lon": 130.3},
    {"code": "MM", "name": "水島", "lat": 34.5333, "lon": 133.7333},
    {"code": "MO", "name": "門司", "lat": 33.95, "lon": 130.95},
    {"code": "MR", "name": "布良", "lat": 34.9167, "lon": 139.8333},
    {"code": "MS", "name": "三角", "lat": 32.6167, "lon": 130.45},
    {"code": "MT", "name": "松山", "lat": 33.8667, "lon": 132.7167},
    {"code": "MU", "name": "室戸岬", "lat": 33.2667, "lon": 134.1667},
    {"code": "MY", "name": "宮古", "lat": 39.65, "lon": 141.9833},
    {"code": "MZ", "name": "舞鶴", "lat": 35.4833, "lon": 135.3833},
    {"code": "N0", "name": "砂津", "lat": 33.9, "lon": 130.8833},
    {"code": "N1", "name": "日明", "lat": 33.9167, "lon": 130.8833},
    {"code": "N5", "name": "対馬比田勝", "lat": 34.65, "lon": 129.4833},
    {"code": "NG", "name": "名古屋", "lat": 35.0833, "lon": 136.8833},
    {"code": "NH", "name": "那覇", "lat": 26.2167, "lon": 127.6667},
    {"code": "NI", "name": "新居浜", "lat": 33.9667, "lon": 133.2667},
    {"code": "NK", "name": "中城湾港", "lat": 26.3333, "lon": 127.8333},
    {"code": "NM", "name": "根室", "lat": 43.35, "lon": 145.5833},
    {"code": "NS", "name": "長崎", "lat": 32.7333, "lon": 129.8667},
    {"code": "O1", "name": "対馬", "lat": 34.2667, "lon": 129.3167},
    {"code": "O3", "name": "苅田", "lat": 33.8, "lon": 131.0},
    {"code": "O5", "name": "八代", "lat": 32.5167, "lon": 130.5667},
    {"code": "O6", "name": "大牟田", "lat": 33.0167, "lon": 130.4167},
    {"code": "O7", "name": "水俣", "lat": 32.2, "lon": 130.3667},
    {"code": "O9", "name": "奄美", "lat": 28.3167, "lon": 129.5333},
    {"code": "OD", "name": "小田原", "lat": 35.2333, "lon": 139.15},
    {"code": "OF", "name": "大船渡", "lat": 39.0167, "lon": 141.75},
    {"code": "OH", "name": "大山の鼻", "lat": 33.9167, "lon": 130.9},
    {"code": "OK", "name": "岡田", "lat": 34.7833, "lon": 139.3833},
    {"code": "OM", "name": "御前崎", "lat": 34.6167, "lon": 138.2167},
    {"code": "ON", "name": "小名浜", "lat": 36.9333, "lon": 140.9},
    {"code": "OR", "name": "奥尻港", "lat": 42.1667, "lon": 139.5167},
    {"code": "OS", "name": "大阪", "lat": 34.65, "lon": 135.4333},
    {"code": "OU", "name": "大浦", "lat": 32.9833, "lon": 130.2167},
    {"code": "OW", "name": "尾鷲", "lat": 34.0833, "lon": 136.2},
    {"code": "Q0", "name": "吉岡", "lat": 41.45, "lon": 140.2333},
    {"code": "Q1", "name": "竜飛", "lat": 41.25, "lon": 140.3833},
    {"code": "Q2", "name": "大湊", "lat": 41.25, "lon": 141.15},
    {"code": "Q6", "name": "釜石", "lat": 39.2667, "lon": 141.8833},
    {"code": "Q8", "name": "広島", "lat": 34.35, "lon": 132.4667},
    {"code": "Q9", "name": "呉", "lat": 34.2333, "lon": 132.55},
    {"code": "QA", "name": "徳山", "lat": 34.0333, "lon": 131.8},
    {"code": "QC", "name": "大分", "lat": 33.2667, "lon": 131.6833},
    {"code": "QD", "name": "佐世保", "lat": 33.15, "lon": 129.7167},
    {"code": "QE", "name": "厳原", "lat": 34.2, "lon": 129.3},
    {"code": "QF", "name": "博多", "lat": 33.6167, "lon": 130.4},
    {"code": "QG", "name": "大泊", "lat": 31.0167, "lon": 130.6833},
    {"code": "QH", "name": "西之表", "lat": 30.7333, "lon": 131.0},
    {"code": "QI", "name": "中之島", "lat": 29.85, "lon": 129.85},
    {"code": "QJ", "name": "名瀬", "lat": 28.4, "lon": 129.5},
    {"code": "QK", "name": "南伊豆", "lat": 34.6333, "lon": 138.8833},
    {"code": "QL", "name": "千葉", "lat": 35.5667, "lon": 140.05},
    {"code": "QN", "name": "横須賀", "lat": 35.2833, "lon": 139.65},
    {"code": "QO", "name": "神津島", "lat": 34.2167, "lon": 139.1333},
    {"code": "QP", "name": "三宅島(阿古)", "lat": 34.0667, "lon": 139.4833},
    {"code": "QQ", "name": "八丈島（神湊）", "lat": 33.1333, "lon": 139.8},
    {"code": "QR", "name": "粟島", "lat": 38.4667, "lon": 139.25},
    {"code": "QS", "name": "横浜", "lat": 35.45, "lon": 139.65},
    {"code": "R1", "name": "平良", "lat": 24.8167, "lon": 125.2833},
    {"code": "RH", "name": "苓北", "lat": 32.4667, "lon": 130.0333},
    {"code": "RZ", "name": "両津", "lat": 38.0833, "lon": 138.4333},
    {"code": "S0", "name": "佐渡", "lat": 38.3167, "lon": 138.5167},
    {"code": "S1", "name": "秋田", "lat": 39.75, "lon": 140.0667},
    {"code": "S2", "name": "船川港", "lat": 39.9167, "lon": 139.85},
    {"code": "S6", "name": "新潟西港", "lat": 37.9333, "lon": 139.0667},
    {"code": "S9", "name": "酒田", "lat": 38.9167, "lon": 139.8167},
    {"code": "SA", "name": "西郷", "lat": 36.2, "lon": 133.3333},
    {"code": "SB", "name": "三蟠", "lat": 34.6, "lon": 133.9833},
    {"code": "SD", "name": "仙台新港", "lat": 38.2667, "lon": 141.0},
    {"code": "SE", "name": "瀬棚", "lat": 42.45, "lon": 139.85},
    {"code": "SG", "name": "塩釜", "lat": 38.3167, "lon": 141.0333},
    {"code": "SH", "name": "下北", "lat": 41.3667, "lon": 141.2333},
    {"code": "SI", "name": "堺", "lat": 34.6, "lon": 135.4667},
    {"code": "SK", "name": "境", "lat": 35.55, "lon": 133.25},
    {"code": "SM", "name": "清水港", "lat": 35.0167, "lon": 138.5167},
    {"code": "SN", "name": "新湊", "lat": 36.7833, "lon": 137.1167},
    {"code": "SO", "name": "白老", "lat": 42.5167, "lon": 141.3167},
    {"code": "SR", "name": "白浜", "lat": 33.6833, "lon": 135.3833},
    {"code": "ST", "name": "洲本", "lat": 34.35, "lon": 134.9},
    {"code": "SU", "name": "片島", "lat": 32.9167, "lon": 132.7},
    {"code": "SZ", "name": "能登", "lat": 37.5, "lon": 137.15},
    {"code": "T1", "name": "金沢", "lat": 36.6167, "lon": 136.6},
    {"code": "T2", "name": "宮津", "lat": 35.5333, "lon": 135.2},
    {"code": "T3", "name": "直江津", "lat": 37.1833, "lon": 138.25},
    {"code": "T6", "name": "津居山", "lat": 35.65, "lon": 134.8333},
    {"code": "TA", "name": "高松", "lat": 34.35, "lon": 134.05},
    {"code": "TB", "name": "鳥羽", "lat": 34.4833, "lon": 136.8167},
    {"code": "TH", "name": "竹原", "lat": 34.3333, "lon": 132.9167},
    {"code": "TI", "name": "田ノ首", "lat": 33.9167, "lon": 130.9167},
    {"code": "TJ", "name": "種子島", "lat": 30.4667, "lon": 130.9667},
    {"code": "TK", "name": "東京", "lat": 35.65, "lon": 139.7667},
    {"code": "TM", "name": "苫小牧西", "lat": 42.6333, "lon": 141.6167},
    {"code": "TN", "name": "淡輪", "lat": 34.3333, "lon": 135.1833},
    {"code": "TS", "name": "土佐清水", "lat": 32.7833, "lon": 132.9667},
    {"code": "TT", "name": "館山", "lat": 34.9833, "lon": 139.85},
    {"code": "TX", "name": "多度津", "lat": 34.2833, "lon": 133.75},
    {"code": "TY", "name": "富山", "lat": 36.7667, "lon": 137.2167},
    {"code": "UC", "name": "内浦", "lat": 35.0167, "lon": 138.8833},
    {"code": "UN", "name": "宇野", "lat": 34.4833, "lon": 133.95},
    {"code": "UR", "name": "浦神", "lat": 33.5667, "lon": 135.9},
    {"code": "UW", "name": "宇和島", "lat": 33.2333, "lon": 132.55},
    {"code": "V7", "name": "須崎", "lat": 33.3833, "lon": 133.3},
    {"code": "WH", "name": "宇部", "lat": 33.9333, "lon": 131.25},
    {"code": "WN", "name": "稚内", "lat": 45.4, "lon": 141.6833},
    {"code": "WY", "name": "和歌山", "lat": 34.2167, "lon": 135.15},
    {"code": "X2", "name": "平戸瀬戸", "lat": 33.3667, "lon": 129.5833},
    {"code": "X3", "name": "郷ノ浦", "lat": 33.75, "lon": 129.6833},
    {"code": "X5", "name": "佐伯", "lat": 32.95, "lon": 131.9667},
    {"code": "X6", "name": "志布志", "lat": 31.4833, "lon": 131.1167},
    {"code": "XM", "name": "敦賀", "lat": 35.6667, "lon": 136.0667},
    {"code": "XO", "name": "七尾", "lat": 37.05, "lon": 136.9667},
    {"code": "XQ", "name": "伏木富山", "lat": 36.8, "lon": 137.0667},
    {"code": "XS", "name": "むつ小川原", "lat": 40.9333, "lon": 141.3833},
    {"code": "XT", "name": "久慈", "lat": 40.2, "lon": 141.8},
    {"code": "YJ", "name": "与那国", "lat": 24.45, "lon": 122.95},
    {"code": "YK", "name": "京浜港", "lat": 35.4667, "lon": 139.6333},
    {"code": "Z1", "name": "油壺", "lat": 35.1667, "lon": 139.6167},
    {"code": "Z3", "name": "伊東", "lat": 34.9, "lon": 139.1333},
    {"code": "Z4", "name": "田子", "lat": 34.8, "lon": 138.7667},
    {"code": "Z5", "name": "焼津", "lat": 34.8667, "lon": 138.3333},
    {"code": "Z6", "name": "細島", "lat": 32.4333, "lon": 131.6667},
    {"code": "Z7", "name": "輪島", "lat": 37.4, "lon": 136.9},
    {"code": "Z8", "name": "忍路", "lat": 43.2167, "lon": 140.8667},
    {"code": "Z9", "name": "海南", "lat": 34.15, "lon": 135.2},
    {"code": "ZA", "name": "浅虫", "lat": 40.9, "lon": 140.8667},
    {"code": "ZB", "name": "鼠ヶ関", "lat": 38.5667, "lon": 139.55},
    {"code": "ZC", "name": "柏崎", "lat": 37.35, "lon": 138.5167},
    {"code": "ZD", "name": "鬼崎", "lat": 34.9, "lon": 136.8167},
    {"code": "ZE", "name": "田後", "lat": 35.6, "lon": 134.3167},
    {"code": "ZF", "name": "勝浦", "lat": 35.1333, "lon": 140.25},
    {"code": "ZG", "name": "三国", "lat": 36.25, "lon": 136.15},
    {"code": "ZH", "name": "久礼", "lat": 33.3333, "lon": 133.25},
    {"code": "ZI", "name": "男鹿", "lat": 39.95, "lon": 139.7},
    {"code": "ZJ", "name": "阿久根", "lat": 32.0167, "lon": 130.1833},
    {"code": "ZK", "name": "須佐", "lat": 34.6333, "lon": 131.6},
    {"code": "ZL", "name": "仮屋", "lat": 33.4667, "lon": 129.85},
    {"code": "ZM", "name": "相馬", "lat": 37.8333, "lon": 140.9667},
    {"code": "ZN", "name": "小木", "lat": 37.8167, "lon": 138.2833},
    {"code": "ZO", "name": "沖縄", "lat": 26.1833, "lon": 127.8167},
    {"code": "ZP", "name": "奥尻", "lat": 42.0833, "lon": 139.4833},
    {"code": "ZQ", "name": "飛島", "lat": 39.1833, "lon": 139.55},
]

BASE_URL = "https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year}/{code}.txt"


def parse_line(line):
    """
    1行（1日分）をパースして (YYYY-MM-DD, {"high": [...], "low": [...]}) を返す。
    満潮・干潮は [["HH:MM", level_cm], ...] の形式。
    """
    if len(line) < 136:
        return None

    try:
        yy = int(line[72:74])
        mm = int(line[74:76])
        dd = int(line[76:78])
    except ValueError:
        return None

    # 気象庁テキストは西暦下2桁。2000年代とみなす（2000-2099）
    year = 2000 + yy
    try:
        date_str = f"{year:04d}-{mm:02d}-{dd:02d}"
        datetime(year, mm, dd)  # バリデーション
    except ValueError:
        return None

    def extract_tides(start):
        """start カラム以降に (時刻4桁 + 潮位3桁) × 4 を取り出す"""
        tides = []
        for i in range(4):
            ofs = start + i * 7
            t_str = line[ofs:ofs + 4]
            l_str = line[ofs + 4:ofs + 7]
            if not t_str.strip() or t_str.strip() == "9999":
                continue
            try:
                hh = int(t_str[:2])
                mn = int(t_str[2:])
                level = int(l_str)
                if level == 999:  # 欠測
                    continue
                tides.append([f"{hh:02d}:{mn:02d}", level])
            except ValueError:
                continue
        return tides

    return date_str, {
        "high": extract_tides(80),   # 81-108カラム（0-indexed: 80-107）
        "low":  extract_tides(108),  # 109-136カラム（0-indexed: 108-135）
    }


def fetch_port(code, year, retries=3):
    """指定港・年のテキストデータを取得。失敗時は再試行。"""
    url = BASE_URL.format(year=year, code=code)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tsukiyoga-tide-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                # 翌年データがまだ公開されていない等
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {code} {year}: {last_err}")


def write_port_json(port, year, text, out_dir):
    """テキストをパースしてJSONに書き出す。書き出した日数を返す。"""
    days = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        result = parse_line(line)
        if result:
            date_str, data = result
            days[date_str] = data

    out = {
        "code": port["code"],
        "name": port["name"],
        "lat": port["lat"],
        "lon": port["lon"],
        "year": year,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "JMA (Japan Meteorological Agency)",
        "days": days,
    }

    out_path = out_dir / f"{port['code']}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(days)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="JMA潮位データ取得")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        help="取得対象年（複数指定可、例: --years 2026 2027）")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.years:
        years = args.years
    else:
        # デフォルト: 今年。 11月以降は翌年も追加
        years = [now.year]
        if now.month >= 11:
            years.append(now.year + 1)

    root = Path(__file__).resolve().parent  # リポジトリルート
    base_out = root / "data" / "tide"
    base_out.mkdir(parents=True, exist_ok=True)

    # 港メタ情報
    ports_meta = {
        "updated_at": now.isoformat(),
        "source": "JMA",
        "ports": [{"code": p["code"], "name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in PORTS],
    }
    with open(base_out / "ports.json", "w", encoding="utf-8") as f:
        json.dump(ports_meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote ports.json ({len(PORTS)} ports)")

    # 各港×各年を処理
    success = 0
    skipped = 0
    failed = 0
    for year in years:
        out_dir = base_out / str(year)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Year {year} ===")
        for port in PORTS:
            try:
                text = fetch_port(port["code"], year)
                if text is None:
                    print(f"  [skip] {port['code']} {port['name']}: no data (404)")
                    skipped += 1
                    continue
                n = write_port_json(port, year, text, out_dir)
                print(f"  [ok]   {port['code']} {port['name']}: {n} days")
                success += 1
                time.sleep(0.5)  # 気象庁への負荷軽減
            except Exception as e:
                print(f"  [FAIL] {port['code']} {port['name']}: {e}", file=sys.stderr)
                failed += 1

    print(f"\nSummary: success={success}, skipped={skipped}, failed={failed}")
    if failed > 0 and success == 0:
        sys.exit(1)  # 全滅ならエラー終了（GitHub Actionsが失敗通知を出す）


if __name__ == "__main__":
    main()
