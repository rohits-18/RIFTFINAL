import React, { useEffect, useState } from 'react';
import { useStore, RunHistoryItem } from '../store/useStore';
import { RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight } from 'lucide-react';

const statusBadge = (status: string) => {
    switch (status) {
        case 'RESOLVED': return 'text-emerald-400 bg-emerald-900/30 border-emerald-700/50';
        case 'FAILED': return 'text-red-400 bg-red-900/30 border-red-700/50';
        case 'IN_PROGRESS': return 'text-blue-400 bg-blue-900/30 border-blue-700/50 animate-pulse';
        case 'PENDING':
        case 'QUEUED': return 'text-amber-400 bg-amber-900/30 border-amber-700/50 animate-pulse';
        default: return 'text-slate-400 bg-slate-800 border-slate-700';
    }
};

const StatusIcon = ({ status }: { status: string }) => {
    if (status === 'RESOLVED') return <CheckCircle2 className="w-3 h-3" />;
    if (status === 'FAILED') return <XCircle className="w-3 h-3" />;
    if (status === 'IN_PROGRESS') return <Loader2 className="w-3 h-3 animate-spin" />;
    return <Clock className="w-3 h-3" />;
};

const repoName = (url: string) => {
    try {
        const parts = url.replace(/\.git$/, '').split('/');
        return parts.slice(-2).join('/');
    } catch { return url; }
};

const RunHistoryPanel = () => {
    const { runHistory, selectRun, fetchRuns, runId } = useStore();
    const [refreshing, setRefreshing] = useState(false);

    const handleRefresh = async () => {
        setRefreshing(true);
        await fetchRuns();
        setTimeout(() => setRefreshing(false), 600);
    };

    return (
        <div className="bg-gradient-to-b from-slate-800 to-slate-800/80 rounded-2xl border border-slate-700/60 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-700/60 flex items-center justify-between">
                <h3 className="text-[11px] font-black uppercase tracking-widest text-slate-400 flex items-center gap-2">
                    🕓 Healing History
                </h3>
                <button
                    onClick={handleRefresh}
                    className="text-slate-500 hover:text-blue-400 transition-colors p-1 rounded"
                    title="Refresh"
                    id="refresh-history-btn"
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
                </button>
            </div>

            <div className="divide-y divide-slate-700/40 max-h-80 overflow-y-auto">
                {runHistory.length === 0 ? (
                    <p className="text-slate-600 text-xs text-center py-8 px-4">No previous runs found.<br />Start a new mission above.</p>
                ) : (
                    runHistory.map((run: RunHistoryItem) => (
                        <button
                            key={run.run_id}
                            id={`run-${run.run_id}`}
                            onClick={() => selectRun(run.run_id)}
                            className={`w-full text-left px-5 py-3 hover:bg-slate-700/30 transition-all group flex items-center justify-between gap-3 ${run.run_id === runId ? 'bg-blue-900/10 border-l-2 border-l-blue-500' : ''}`}
                        >
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black border ${statusBadge(run.ci_status)}`}>
                                        <StatusIcon status={run.ci_status} />
                                        {run.ci_status}
                                    </span>
                                    <span className="text-slate-500 text-[10px] font-mono">{run.total_fixes} fixes</span>
                                </div>
                                <p className="text-slate-300 text-xs font-medium truncate">{repoName(run.repo_url)}</p>
                                <p className="text-slate-600 text-[10px] font-mono truncate">{run.branch_name}</p>
                            </div>
                            <ChevronRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 flex-shrink-0 transition-colors" />
                        </button>
                    ))
                )}
            </div>
        </div>
    );
};

export default RunHistoryPanel;
