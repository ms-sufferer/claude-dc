# Discord w Claude Code

Plugin do Claude Code, który pozwala czytać firmowy serwer Discord: listę kanałów i historię wiadomości.
Serwer jest **tylko do odczytu**: narzędzia do wysyłania wiadomości, reakcji, moderacji, kanałów i ról są wyłączone w kodzie.

## Instalacja (jednorazowo, ok. 5 minut)

**1. Zainstaluj `uv`** (uruchamia serwer, sam pobiera potrzebnego Pythona). W PowerShellu:

```powershell
winget install --id astral-sh.uv -e
```

**2. Ustaw token bota.** Skopiuj token otrzymany od administratora do schowka, pobierz [ustaw-token.ps1](ustaw-token.ps1) i uruchom:

```powershell
powershell -ExecutionPolicy Bypass -File .\ustaw-token.ps1
```

Tokenu nikomu nie przekazuj i nie wklejaj do czatu.

**3. Zamknij i otwórz ponownie Claude Code**, żeby widział nową zmienną i `uv`.

**4. Zaloguj Gita do GitHuba.** Repozytorium jest prywatne, a Claude Code nie pokazuje okna logowania. Uruchom raz w PowerShellu i zaloguj się w okienku (**Sign in with your browser**) na konto GitHub z dostępem do repo:

```powershell
git ls-remote https://github.com/ms-sufferer/claude-dc.git
```

Jeśli na komputerze jest już zalogowane inne konto GitHub bez dostępu, dopisz swój login przed `github.com`, np. `https://jan-kowalski@github.com/...`, tu i w kroku 5.

**5. Dodaj plugin.** W Claude Code wpisz kolejno (pełny adres HTTPS, skrót `ms-sufferer/claude-dc` próbuje SSH):

```
/plugin marketplace add https://github.com/ms-sufferer/claude-dc.git
/plugin install discord@ms-sufferer
```

**6. Otwórz nową sesję** i napisz np.:

> Pokaż kanały serwera Discord, które widzi bot

> Przeczytaj ostatnie 100 wiadomości z kanału #ogólny i podsumuj ustalenia

## Co potrafi

- `read_messages`: do 1000 wiadomości na wywołanie, zakres `after`/`before` (ID wiadomości albo data, np. `2026-01-01`),
  razem z załącznikami, osadzeniami i odpowiedziami. Gdy wynik jest za duży, kończy się podpowiedzią, od którego miejsca czytać dalej.
- `get_attachment`: pokazuje zdjęcia z wiadomości (do 5 na raz, każde do 5 MB) i treść plików tekstowych.

## Aktualizacja

```
/plugin marketplace update ms-sufferer
```

## Rozwiązywanie problemów

- **Serwer `discord` się nie łączy:** sprawdź w PowerShellu `uv --version` oraz czy `[Environment]::GetEnvironmentVariable('DISCORD_TOKEN','User')` nie jest puste. Po zmianie zawsze uruchom Claude Code ponownie.
- **Bot nie widzi kanału:** dostęp bota do kanałów ustawia administrator w Discordzie.

## Dla administratora

- Bot: https://discord.com/developers/applications. Wymagane: **Message Content Intent** i **Server Members Intent**.
- Zaproszenie tylko z odczytem: `https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot&permissions=66560`
- Kanały ogranicza się nadpisaniem uprawnień View Channel dla bota na kanałach lub kategoriach.
- Po wycieku tokenu: **Reset Token** w Developer Portal i rozesłanie nowego.

Kod serwera to fork [hanweg/mcp-discord](https://github.com/hanweg/mcp-discord) (licencja MIT) z trybem tylko do odczytu i przypiętą wersją `mcp<2`.
