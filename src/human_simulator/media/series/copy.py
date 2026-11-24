"""Voiceover scripts, SRT, and social captions. No clinical claims."""

from __future__ import annotations

from pathlib import Path

from human_simulator.media.series.constants import EVIDENCE_DIR, FPS, PUBLIC_MEDIA_DIR


def _srt(cues: list[dict[str, str | int]], fps: int = FPS) -> str:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        start = _ts(int(cue["from"]) / fps)
        end = _ts(int(cue["to"]) / fps)
        lines.append(f"{index}\n{start} --> {end}\n{cue['text']}\n")
    return "\n".join(lines) + "\n"


def _ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


SCRIPTS: dict[str, dict[str, str]] = {
    "Roadmap01": {
        "en": (
            "A connected pilot source contains longitudinal records for 43,856 subjects. "
            "Eight thousand five hundred eighty-eight had three or more appointments. "
            "Eight thousand two hundred sixty-two also had laboratory history. "
            "From that eligible set, one hundred subjects entered the first bounded technical cohort. "
            "The source also holds sixty-eight point one thousand appointments, "
            "eight hundred seventy-four thousand laboratory result records, "
            "and one point three seven million result items. "
            "Volume alone is not enough. Longitudinal structure is what makes simulation testable. "
            "These are aggregated counts from one connected pilot source. No patient record is displayed."
        ),
        "ru": (
            "Подключённый пилотный источник содержит продольные данные 43 856 субъектов. "
            "Восемь тысяч пятьсот восемьдесят восемь имели три и более приёма. "
            "Восемь тысяч двести шестьдесят два также имели лабораторную историю. "
            "Из этого множества сто субъектов вошли в первую ограниченную техническую когорту. "
            "В источнике также шестьдесят восемь целых одна тысяча приёмов, "
            "восемьсот семьдесят четыре тысячи лабораторных записей "
            "и один миллион триста семьдесят тысяч позиций результатов. "
            "Одного объёма данных недостаточно. Проверяемой симуляцию делает продольная структура. "
            "Это агрегаты одного пилотного источника. Ни одна пациентская запись не показана."
        ),
        "linkedin": (
            "UHBSE series 1/6 — The longitudinal data problem.\n"
            "A connected pilot source contains longitudinal records for 43,856 subjects. "
            "100 entered the first bounded technical cohort.\n"
            "Volume alone is not enough. Longitudinal structure is what makes simulation testable.\n"
            "Aggregates only. No patient record. Technical slice, not a clinical model."
        ),
        "x": (
            "A connected pilot source: 43,856 subjects. 100 in the first bounded technical cohort.\n"
            "Volume alone ≠ testable simulation. Longitudinal structure does.\n"
            "UHBSE 1/6 · aggregates only · no patient record"
        ),
    },
    "Roadmap02": {
        "en": (
            "Most of the work happens before the model. "
            "Twenty-nine thousand four hundred sixty-four laboratory records were available. "
            "Four thousand were selected for the bounded technical slice. "
            "Six thousand five hundred thirty-eight result items were available. "
            "Six thousand two hundred ninety-one were selected. "
            "Five thousand three hundred thirty-three became valid canonical components. "
            "Nine hundred twenty-seven rows were missing source values. "
            "Thirty-one had invalid numeric representations. "
            "Rejected rows are part of traceable data engineering. "
            "A clinical database becomes model-ready only after its uncertainty, missingness and provenance are made explicit."
        ),
        "ru": (
            "Большая часть работы происходит до модели. "
            "Двадцать девять тысяч четыреста шестьдесят четыре лабораторные записи были доступны. "
            "Четыре тысячи отобраны в ограниченный технический срез. "
            "Шесть тысяч пятьсот тридцать восемь позиций результатов были доступны. "
            "Шесть тысяч двести девяносто одна отобрана. "
            "Пять тысяч триста тридцать три стали валидными каноническими компонентами. "
            "Девятьсот двадцать семь строк без исходного значения. "
            "Тридцать одна — с некорректным числовым представлением. "
            "Отбраковка — часть прослеживаемой инженерии данных. "
            "Клиническая база становится пригодной для модели только когда неопределённость, пропуски и происхождение сделаны явными."
        ),
        "linkedin": (
            "UHBSE series 2/6 — What survives normalization.\n"
            "29,464 available lab records → 5,333 valid canonical components.\n"
            "Rejected rows are part of traceable data engineering.\n"
            "No patient record. No source table names."
        ),
        "x": (
            "Most of the work happens before the model.\n"
            "29,464 labs → 5,333 valid components.\n"
            "UHBSE 2/6 · rejects are data engineering"
        ),
    },
    "Roadmap03": {
        "en": (
            "Before we simulate a future, we need a state the computer can understand. "
            "The bounded slice holds twelve thousand five hundred forty-four source records, "
            "one hundred subjects, two hundred characteristics, two thousand one hundred fifty-three encounters, "
            "four thousand observations, and five thousand three hundred thirty-three observation components. "
            "Twenty-four thousand three hundred thirty-one records carry valid provenance. "
            "Ten timelines. Five hundred ninety-eight timeline events. Ten starting-state snapshots. "
            "The picture uses a synthetic composite, not a real person. No laboratory values are shown. "
            "History collapses into an evidence state snapshot with observed, computed and synthetic layers kept apart. "
            "Every computed state must remain traceable to the evidence that created it."
        ),
        "ru": (
            "Прежде чем симулировать будущее, нужно состояние, которое компьютер может понять. "
            "В ограниченном срезе двенадцать тысяч пятьсот сорок четыре исходные записи, "
            "сто субъектов, двести характеристик, две тысячи сто пятьдесят три встречи, "
            "четыре тысячи наблюдений и пять тысяч триста тридцать три компонента. "
            "Двадцать четыре тысячи триста тридцать одна запись с валидным происхождением. "
            "Десять временных линий. Пятьсот девяносто восемь событий. Десять снимков стартового состояния. "
            "На экране синтетический композит, не реальный человек. Лабораторные значения не показаны. "
            "История сжимается в снимок состояния с раздельными слоями observed, computed и synthetic. "
            "Каждое вычисленное состояние должно оставаться связанным с исходными наблюдениями, из которых оно было построено."
        ),
        "linkedin": (
            "UHBSE series 3/6 — From history to state.\n"
            "12,544 source records → EvidenceStateSnapshot.\n"
            "Observed, computed and synthetic stay in separate layers.\n"
            "SYNTHETIC_COMPOSITE only. No laboratory values. No real subject."
        ),
        "x": (
            "Before a future, a state the computer can understand.\n"
            "Observed / computed / synthetic stay apart.\n"
            "UHBSE 3/6 · synthetic composite · no lab values"
        ),
    },
    "Roadmap04": {
        "en": (
            "We can now fork a biological state without changing its original history. "
            "One shared trajectory. A post-step checkpoint at week two. "
            "Two branches: a counterfactual continuation, and a controlled event branch. "
            "At week three a synthetic controlled event is applied. "
            "Same checkpoint hash. First divergence at week three. One changed variable. Different final hashes. "
            "Parent state, parent history and parent events remain unchanged. "
            "Rollback reproduces the original final hash. "
            "Same starting state. One controlled change. Two traceable continuations. "
            "This is a technical synthetic intervention test. No biological or clinical effect is claimed."
        ),
        "ru": (
            "Теперь можно ветвить биологическое состояние, не меняя исходную историю. "
            "Одна общая траектория. Контрольная точка после шага на неделе два. "
            "Две ветки: контрфактическое продолжение и ветка с контролируемым событием. "
            "На неделе три применяется синтетическое контролируемое событие. "
            "Тот же хеш контрольной точки. Первое расхождение на неделе три. Одна изменённая переменная. Разные финальные хеши. "
            "Родительское состояние, история и события не меняются. "
            "Откат воспроизводит исходный финальный хеш. "
            "Одно стартовое состояние. Одно контролируемое изменение. Два прослеживаемых продолжения. "
            "Это технический синтетический тест. Биологический или клинический эффект не утверждается."
        ),
        "linkedin": (
            "UHBSE series 4/6 — Forking a biological state.\n"
            "Checkpoint week 2. Synthetic event week 3. Parent history unchanged. Rollback matches the original hash.\n"
            "Technical synthetic intervention test. No biological or clinical effect is claimed."
        ),
        "x": (
            "Fork a state without rewriting its history.\n"
            "Same start. One controlled change. Two continuations.\n"
            "UHBSE 4/6 · technical test · no clinical effect claimed"
        ),
    },
    "Roadmap05": {
        "en": (
            "A simulation should be able to fail. "
            "We reject future-data leakage. We detect parent-state and parent-history mutation. "
            "A no-op event cannot claim a fork effect. The same seed must replay the same trajectory. "
            "Rollback must reproduce the original continuation. "
            "Provenance without required fields is rejected. A modified contract hash is rejected. "
            "Forty-four clean-room tests passed. "
            "Green PASS appears only after the check runs. An expected FAIL is part of the design. "
            "We test failure modes before we trust performance. "
            "Technical core: verified. Clinical validation: not started."
        ),
        "ru": (
            "Симуляция должна уметь провалиться. "
            "Утечка будущих данных отклоняется. Мутация родительского состояния и истории обнаруживается. "
            "Событие без эффекта не может считаться ветвлением. Тот же seed обязан повторить ту же траекторию. "
            "Откат должен воспроизвести исходное продолжение. "
            "Происхождение без обязательных полей отклоняется. Изменённый хеш контракта отклоняется. "
            "Сорок четыре теста чистой комнаты прошли. "
            "Зелёный PASS появляется только после вычисления. Ожидаемый FAIL — часть конструкции. "
            "Сначала проверяем режимы отказа, потом доверяем качеству. "
            "Техническое ядро: проверено. Клиническая валидация: не начата."
        ),
        "linkedin": (
            "UHBSE series 5/6 — How we test the engine.\n"
            "44 clean-room tests passed. Future leakage, parent mutation, no-op forks, rollback and contract hashes are checked.\n"
            "Technical core verified. Clinical validation not started."
        ),
        "x": (
            "A simulation should be able to fail.\n"
            "44 clean-room tests passed.\n"
            "UHBSE 5/6 · technical core verified · clinical validation not started"
        ),
    },
    "Roadmap06": {
        "en": (
            "The first exploratory retrospective backtest is complete. "
            "Thirty subjects with consecutive pairs. Forty strict consecutive pairs. "
            "A subject-disjoint exploratory split. "
            "Three models: persistence, empirical trend, and a first learned Ridge baseline. "
            "On the held-out test of two subjects and two pairs, learned MAE was about 0.524 "
            "and persistence MAE was 1.425. "
            "Lower error is not an incremental signal when the test has only two independent subjects. "
            "Uncertainty calibration: insufficient data. "
            "Clinical validation: not started. Intervention-response modeling: not started."
        ),
        "ru": (
            "Первый exploratory retrospective backtest завершён. "
            "Тридцать субъектов с consecutive pairs. Сорок строго последовательных пар. "
            "Subject-disjoint exploratory split. "
            "Три модели: persistence, empirical trend и first learned Ridge baseline. "
            "На held-out тесте из двух субъектов и двух пар learned MAE около 0.524, "
            "persistence MAE — 1.425. "
            "Меньшая ошибка не является инкрементальным сигналом, когда тест содержит только два независимых субъекта. "
            "Калибровка неопределённости: недостаточно данных. "
            "Клиническая валидация: не начата. Intervention-response modeling: не начато."
        ),
        "linkedin": (
            "UHBSE series 6/6 — The first scientific test.\n"
            "First exploratory retrospective backtest complete.\n"
            "Learned MAE ≈ 0.524 vs persistence 1.425 on a 2-subject / 2-pair test.\n"
            "NO INCREMENTAL SIGNAL CLAIMED. Uncertainty calibration: insufficient data.\n"
            "Clinical validation not started."
        ),
        "x": (
            "First learned model beat persistence on MAE.\n"
            "Test size: 2 subjects / 2 pairs → no signal claimed.\n"
            "UHBSE 6/6 · exploratory · clinical validation not started"
        ),
    },
}


def write_copy(root: Path, fixture: dict) -> dict[str, str]:
    evidence = root / EVIDENCE_DIR
    media = root / PUBLIC_MEDIA_DIR
    scripts_dir = evidence / "voiceover"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    by_id = {episode["id"]: episode for episode in fixture["episodes"]}
    for eid, pack in SCRIPTS.items():
        episode = by_id[eid]
        slug = episode["slug"]
        episode_dir = media / slug
        episode_dir.mkdir(parents=True, exist_ok=True)
        for lang in ("en", "ru"):
            script_path = scripts_dir / f"{slug}.{lang}.txt"
            script_path.write_text(pack[lang].strip() + "\n", encoding="utf-8")
            written[f"{eid}.{lang}.script"] = str(script_path)
            media_script = episode_dir / f"voiceover.{lang}.txt"
            media_script.write_text(pack[lang].strip() + "\n", encoding="utf-8")
            srt_path = episode_dir / f"captions.{lang}.srt"
            if lang == "en":
                srt_path.write_text(_srt(episode["captions"]), encoding="utf-8")
            else:
                srt_path.write_text(_ru_srt(eid, episode["captions"]), encoding="utf-8")
            written[f"{eid}.{lang}.srt"] = str(srt_path)
        (episode_dir / "linkedin.txt").write_text(pack["linkedin"].strip() + "\n", encoding="utf-8")
        (episode_dir / "x-threads.txt").write_text(pack["x"].strip() + "\n", encoding="utf-8")
        (episode_dir / "cover-headline.txt").write_text(episode["cover_headline"] + "\n", encoding="utf-8")
    return written


def _ru_srt(eid: str, en_cues: list[dict]) -> str:
    ru = {
        "Roadmap01": [
            "43 856 вошли. 100 — первая когорта.",
            "Пригодность — продольная, не просто численность.",
            "Приёмы, лаборатории, позиции — агрегаты источника.",
            "Объёма недостаточно. Продольная структура делает симуляцию проверяемой.",
        ],
        "Roadmap02": [
            "Большая часть работы происходит до модели.",
            "Доступные лаборатории → отобранные → валидные компоненты.",
            "Отбраковка ожидаема: пропуски и некорректные числа.",
            "Неопределённость, пропуски и происхождение должны быть явными.",
        ],
        "Roadmap03": [
            "Прежде чем симулировать будущее, нужно состояние для компьютера.",
            "Исходные записи, субъекты, покрытие происхождения.",
            "Синтетический композит из историй и событий.",
            "Observed, computed и synthetic остаются в разных слоях.",
        ],
        "Roadmap04": [
            "Ветвление состояния без изменения исходной истории.",
            "Контрольная точка. Тот же хеш.",
            "Контролируемое событие. Родительская история не меняется.",
            "Откат воспроизводит исходный финальный хеш.",
        ],
        "Roadmap05": [
            "Симуляция должна уметь провалиться.",
            "PASS — только после проверки. Ожидаемый FAIL — часть конструкции.",
            "Тесты чистой комнаты прошли. Техническое ядро проверено.",
            "Клиническая валидация не начата.",
        ],
        "Roadmap06": [
            "Первый exploratory retrospective backtest завершён.",
            "Persistence MAE и learned MAE. Тест: 2 субъекта / 2 пары.",
            "Сигнал не заявлен. Клиническая валидация не начата.",
            "Меньшая ошибка — не научное утверждение на двух субъектах.",
        ],
    }
    cues = []
    for cue, text in zip(en_cues, ru[eid], strict=True):
        cues.append({"from": cue["from"], "to": cue["to"], "text": text})
    return _srt(cues)
