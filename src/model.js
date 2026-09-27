export const INTERVALS = [0, 3600, 21600, 43200, 86400, 604800];
export function isDue(now, lastSuccess, interval, retryAt = 0) {
    return interval > 0 && now >= retryAt && (lastSuccess <= 0 || now - lastSuccess >= interval || lastSuccess > now);
}
export function nextLabel(lastSuccess, interval) {
    if (!interval) return 'Manual changes only';
    if (!lastSuccess) return 'Due now';
    return `Next change: ${new Date((lastSuccess + interval) * 1000).toLocaleString()}`;
}
