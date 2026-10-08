type Level = "debug" | "info" | "warn" | "error";
type Fields = Record<string, unknown>;

function write(level: Level, message: string, fields: Fields = {}): void {
  const line = JSON.stringify({ time: new Date().toISOString(), level, message, ...fields });
  if (level === "warn" || level === "error") {
    console.error(line);
  } else {
    console.log(line);
  }
}

export const logger = {
  debug: (message: string, fields?: Fields) => write("debug", message, fields),
  info: (message: string, fields?: Fields) => write("info", message, fields),
  warn: (message: string, fields?: Fields) => write("warn", message, fields),
  error: (message: string, fields?: Fields) => write("error", message, fields),
};
