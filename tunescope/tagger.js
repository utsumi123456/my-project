// TuneScope クリップタガー ([js] / LiveAPI)
// "tag 8A 124" を受けて、再生中（なければ選択中）クリップ名に [8A 124] を付与
autowatch = 1;

function tag(cam, bpm) {
    var clip = null;
    var track = new LiveAPI("this_device canonical_parent");
    if (track && track.id != 0) {
        var psi = parseInt(track.get("playing_slot_index"));
        if (psi >= 0) {
            clip = new LiveAPI("this_device canonical_parent clip_slots " + psi + " clip");
        }
    }
    if (!clip || clip.id == 0) {
        clip = new LiveAPI("live_set view detail_clip"); // 選択中クリップ
    }
    if (!clip || clip.id == 0) {
        post("TuneScope: タグ対象のクリップが見つかりません（再生中/選択中クリップなし）\n");
        return;
    }
    var name = String(clip.get("name"));
    name = name.replace(/^\[[^\]]*\]\s*/, ""); // 既存タグを除去
    var newName = "[" + cam + " " + Math.round(Number(bpm)) + "] " + name;
    clip.set("name", newName);
    post("TuneScope: renamed -> " + newName + "\n");
}
