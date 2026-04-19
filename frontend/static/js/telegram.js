const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

export const getTelegramId   = () => tg?.initDataUnsafe?.user?.id ?? null;
export const getTelegramUser = () => tg?.initDataUnsafe?.user ?? null;
export const getTheme        = () => tg?.colorScheme ?? "light";
