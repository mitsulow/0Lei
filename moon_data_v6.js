/* ツキヨガ v6 ─ 月の拡張データ（ヒルマツリ・ヨルマツリ・両手位置・浮世絵アイコン） */
(function () {
  'use strict';

  // === 月の角度ロジック ====================================================
  // 旧暦日数に応じて両手の開く角度（°）。
  // 1日(新月)=0°（合掌・上）、7日(上弦)=168°（≈水平）、15日(満月)=360°（合掌・下）
  // 23日(下弦)=552°（水平・逆）、30日=720°（合掌・上に戻る）
  function totalOpenDeg(d) {
    return (d - 1) * 24;
  }

  // 角度（°）→ 時計表記。12時=0°、3時=90°、6時=180°、9時=270°、30分単位で丸め。
  function angleToClock(deg) {
    let n = ((deg % 360) + 360) % 360;
    const hourFloat = n / 30;
    const half = Math.round(hourFloat * 2) / 2; // 0, 0.5, 1, 1.5, ...
    let h = Math.floor(half);
    const m = Math.round((half - h) * 60); // 0 or 30
    if (h === 0) h = 12;
    if (h > 12) h -= 12;
    return m === 0 ? `${h}時` : `${h}:${String(m).padStart(2, '0')}`;
  }

  function getHandClocks(d) {
    const halfDeg = totalOpenDeg(d) / 2;
    const norm = (a) => ((a % 360) + 360) % 360;
    return {
      right: angleToClock(halfDeg),
      left: angleToClock(-halfDeg),
      rightDeg: norm(halfDeg),
      leftDeg: norm(-halfDeg),
    };
  }

  // ヒルマツリ・ヨルマツリ時刻
  // 1日 12:00 起点、各日 48 分シフト（月の南中の概算遅延）
  function pad2(n) { return String(n).padStart(2, '0'); }
  function minToHM(min) {
    const m = ((min % 1440) + 1440) % 1440;
    const m30 = Math.round(m / 30) * 30;
    let hh = Math.floor(m30 / 60) % 24;
    let mm = m30 % 60;
    if (mm === 60) { hh = (hh + 1) % 24; mm = 0; }
    return `${pad2(hh)}:${pad2(mm)}`;
  }
  function getMatsuriTimes(d) {
    const offset = (d - 1) * 48;
    const hiruMin = 12 * 60 + offset;
    const yoruMin = hiruMin + 12 * 60;
    return { hiru: minToHM(hiruMin), yoru: minToHM(yoruMin) };
  }

  // === 30日のメタ情報（既存の MOON_NAMES_30 を拡張） =======================
  const META_30 = {
    1:  { angle: 0,   note: '太陽と月が重なる、光と闇のひとつになる日。両手で合掌、月のひと巡りの起点。' },
    2:  { angle: 24,  note: '生まれて二日目の月。手のひらがわずかに開きはじめる。' },
    3:  { angle: 48,  note: '夕方の西空に細い月。月が「目を覚ます」最初の姿。' },
    4:  { angle: 72,  note: '眉のようにすっと弧を引く月。' },
    5:  { angle: 96,  note: '夕暮れに親しむ夕月。日々の祈りの始まり。' },
    6:  { angle: 120, note: '上弦に向かう月。両手の弧が大きくなる。' },
    7:  { angle: 144, note: '上弦の半月。両手は左右にひらき水平に近づく。聖点。' },
    8:  { angle: 168, note: '半月を過ぎ、丸みを増す宵の月。' },
    9:  { angle: 192, note: '九夜目の月。徐々に下方向へ手が回る。' },
    10: { angle: 216, note: '十日夜（とおかんや）。秋の収穫祭にゆかりの月。' },
    11: { angle: 240, note: '満ちつつある十一夜の月。' },
    12: { angle: 264, note: '十二夜。望月（満月）が近づく。' },
    13: { angle: 288, note: '可惜夜（あたらよ）。沖縄民謡「月ぬ美しゃ十日三日」。月が最も美しいとされる前夜。' },
    14: { angle: 312, note: '待宵（まちよい）。明日の満月を待つ月。' },
    15: { angle: 336, note: '満月、隈無し（くまなし）。両手は下で合わさり、地に還る。聖点。' },
    16: { angle: 360, note: '十六夜（いざよい）。少しためらうように昇る月。' },
    17: { angle: 384, note: '立待月（たちまちづき）。立って待つほどで昇る月。' },
    18: { angle: 408, note: '居待月（いまちづき）。座って待つ月。' },
    19: { angle: 432, note: '寝待月（ねまちづき）。寝て待つほど遅い月。' },
    20: { angle: 456, note: '更待月（ふけまちづき）。夜更けに昇る月。' },
    21: { angle: 480, note: '二十一夜の月。' },
    22: { angle: 504, note: '二十二夜の月。下弦が近い。' },
    23: { angle: 528, note: '下弦の半月、有明（ありあけ）。明け方の空に残る月。聖点。' },
    24: { angle: 552, note: '下弦を過ぎた二十四夜の月。' },
    25: { angle: 576, note: '星合（ほしあひ）。星々と語らう細い月。' },
    26: { angle: 600, note: '名残月（なごりづき）。月の名残りを惜しむ。' },
    27: { angle: 624, note: '暁（あかつき）。夜明け前の月。' },
    28: { angle: 648, note: '曙（あけぼの）。空が白む頃に残る細い月。' },
    29: { angle: 672, note: '月籠（つごもり）。月が隠れる前夜。' },
    30: { angle: 696, note: '晦日（みそか）。月のひと巡りの終わり、次のツキタチへ。' },
  };

  // 体位・天体担当の規則
  function getBodyPosition(isHiru) {
    return isHiru ? '南向きに立つ' : '北向きに座る';
  }
  function getHandTargets(isHiru) {
    return isHiru
      ? { right: '太陽', left: '月' }
      : { right: '月',   left: '太陽' };
  }

  // === 公開API ============================================================
  // 既存の MOON_NAMES_30 をマージ拡張
  function extendMoonNames(existing) {
    const out = {};
    for (let d = 1; d <= 30; d++) {
      const base = (existing && existing[d]) || {};
      const meta = META_30[d];
      const hands = getHandClocks(d);
      const times = getMatsuriTimes(d);
      out[d] = Object.assign({}, base, {
        angle: meta.angle,
        note: base.note || meta.note,
        icon: `./moon_icons/moon_${pad2(d)}.png`,
        hiru: {
          time: times.hiru,
          clockRight: hands.right, clockLeft: hands.left,
          clockRightDeg: hands.rightDeg, clockLeftDeg: hands.leftDeg,
        },
        yoru: {
          // ヨルマツリは右手＝月、左手＝太陽。ヒルマツリの左右が反転
          time: times.yoru,
          clockRight: hands.left,  clockLeft: hands.right,
          clockRightDeg: hands.leftDeg, clockLeftDeg: hands.rightDeg,
        },
        // 体位
        hiruBody: '南向きに立つ',
        yoruBody: '北向きに座る',
        // 天体担当
        hiruRightTarget: '太陽', hiruLeftTarget: '月',
        yoruRightTarget: '月',   yoruLeftTarget: '太陽',
      });
    }
    return out;
  }

  // window 名前空間に公開
  window.MoonDataV6 = {
    META_30,
    totalOpenDeg,
    angleToClock,
    getHandClocks,
    getMatsuriTimes,
    extendMoonNames,
    getBodyPosition,
    getHandTargets,
  };
})();
