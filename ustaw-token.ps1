# Zapisuje token bota Discord w zmiennej srodowiskowej uzytkownika DISCORD_TOKEN.
# Przed uruchomieniem skopiuj token do schowka. Skrypt go sprawdzi i wyczysci schowek.

$token = (Get-Clipboard -Raw)
if ($token) { $token = $token.Trim().Trim('"') }
if (-not ($token -match '^[\w-]{20,}\.[\w-]{4,}\.[\w-]{20,}$')) {
    Write-Host 'W schowku nie ma tokenu bota Discord (trzy czesci rozdzielone kropkami, ok. 70 znakow).' -ForegroundColor Red
    Write-Host 'Skopiuj token otrzymany od administratora i uruchom skrypt ponownie.'
    exit 1
}

[Environment]::SetEnvironmentVariable('DISCORD_TOKEN', $token, 'User')
Set-Clipboard -Value ' '
Write-Host 'Token zapisany. Zamknij i otworz ponownie Claude Code (cala aplikacje lub terminal).' -ForegroundColor Green
