from deskai.personality import PersonalitySettings, personality_prompt


def test_personality_settings_persist(tmp_path) -> None:
    path = tmp_path / "personality.json"
    expected = PersonalitySettings(warmth=2, wit=3, opinions=3, verbosity=0)

    expected.save(path)

    assert PersonalitySettings.load(path) == expected


def test_personality_prompt_encourages_preferences_without_fake_experience() -> None:
    prompt = personality_prompt(PersonalitySettings())

    assert "answer directly" in prompt
    assert "persona-level tastes" in prompt
    assert "real-world experiences" in prompt
    assert "citations" in prompt
    assert "Sushi? Absolutely" in prompt


def test_invalid_personality_file_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "personality.json"
    path.write_text('{"wit": 99}', encoding="utf-8")

    assert PersonalitySettings.load(path) == PersonalitySettings()


def test_quiet_personality_uses_restrained_demonstrations() -> None:
    prompt = personality_prompt(
        PersonalitySettings(warmth=1, wit=0, opinions=1, verbosity=0)
    )

    assert "Yes. Nigiri is simple" in prompt
    assert "chaotic spicy-tuna" not in prompt
