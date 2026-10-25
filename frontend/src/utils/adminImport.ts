export function isAutoQuoteBatch(fileName: string): boolean {
  return fileName.startsWith("自动生成-");
}

export function joinWarnings(warnings: string[] | undefined): string | null {
  if (!warnings?.length) return null;
  return warnings.join("；");
}
