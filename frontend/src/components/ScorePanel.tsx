import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import { CheckCircle2, AlertOctagon, Timer, BarChart3, GitBranch, Users, User, Globe } from 'lucide-react';

const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
};

const ScorePanel = () => {
    const { currentResult } = useStore();
    const [elapsedLive, setElapsedLive] = useState(0);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Live timer while run is in progress
    useEffect(() => {
        if (!currentResult) return;
        const isFinal = ['RESOLVED', 'FAILED', 'PARTIAL'].includes(currentResult.ci_status);
        if (timerRef.current) clearInterval(timerRef.current);
        if (!isFinal && currentResult.start_time) {
            const tick = () => {
                const startTime = currentResult.start_time || (Date.now() / 1000);
                setElapsedLive(Math.max(0, Math.round(Date.now() / 1000 - startTime)));
            };
            tick();
            timerRef.current = setInterval(tick, 1000);
        } else {
            setElapsedLive(Number(currentResult.elapsed_seconds) || 0);
        }
        return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }, [currentResult?.run_id, currentResult?.ci_status]);

    if (!currentResult) return null;

    const { scoring, ci_status, total_fixes, total_failures, repo_url, branch_name, team_name, leader_name } = currentResult;
    const isFinal = ['RESOLVED', 'FAILED', 'PARTIAL'].includes(ci_status);
    const isResolved = ci_status === 'RESOLVED';
    const isPartial = ci_status === 'PARTIAL';
    const isPending = ['PENDING', 'QUEUED'].includes(ci_status);
    const isRunning = ci_status === 'IN_PROGRESS' || ci_status === 'RUNNING';

    // Score bar percentages (cap at 100)
    const scoreMax = 120;
    const baseBar = Math.min(100, ((scoring?.base_score || 0) / scoreMax) * 100);
    const speedBar = Math.min(100, ((scoring?.speed_factor || 0) / 20) * 100);
    const penaltyBar = Math.min(100, ((scoring?.regression_penalty || 0) / 20) * 100);
    const finalBar = Math.min(100, ((scoring?.final_ci_score || 0) / scoreMax) * 100);

    const statusColor = isResolved
        ? 'text-emerald-400 bg-emerald-900/20 border-emerald-500/50'
        : isPartial
            ? 'text-amber-400 bg-amber-900/20 border-amber-500/50'
            : isPending
                ? 'text-amber-400 bg-amber-900/20 border-amber-500/50'
                : isRunning
                    ? 'text-blue-400 bg-blue-900/20 border-blue-500/50'
                    : 'text-red-400 bg-red-900/20 border-red-500/50';

    return (
        <div className="bg-gradient-to-br from-slate-800 to-slate-800/80 rounded-2xl border border-slate-700/60 overflow-hidden shadow-2xl">
            {/* Header */}
            <div className="px-6 py-4 border-b border-slate-700/50 flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                    <h2 className="text-sm font-black uppercase tracking-widest text-slate-300 flex items-center gap-2 mb-1">
                        📊 Analysis Report
                    </h2>
                    <p className="text-xs text-slate-500 font-mono truncate">{repo_url}</p>
                </div>
                <span className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full font-black text-[11px] border ${statusColor} ${(isRunning || isPending) ? 'animate-pulse' : ''}`}>
                    {isResolved && <CheckCircle2 className="w-3.5 h-3.5" />}
                    {isPartial && <CheckCircle2 className="w-3.5 h-3.5 opacity-70" />}
                    {!isResolved && !isPartial && <AlertOctagon className="w-3.5 h-3.5" />}
                    {ci_status}
                </span>
            </div>

            {/* Run Summary Card (requirement #2) */}
            <div className="px-6 py-4 grid grid-cols-2 md:grid-cols-4 gap-3 border-b border-slate-700/50">
                <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-700/40 flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><Users className="w-3 h-3" /> Team</span>
                    <span className="text-sm font-black text-slate-200 truncate">{team_name || '—'}</span>
                </div>
                <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-700/40 flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><User className="w-3 h-3" /> Leader</span>
                    <span className="text-sm font-black text-slate-200 truncate">{leader_name || '—'}</span>
                </div>
                <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-700/40 flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><GitBranch className="w-3 h-3" /> Branch</span>
                    <span className="text-xs font-bold text-blue-300/90 font-mono truncate">{branch_name}</span>
                </div>
                <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-700/40 flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><Timer className="w-3 h-3" /> Time</span>
                    <span className={`text-sm font-black ${isFinal ? 'text-purple-300' : 'text-orange-300'}`}>
                        {isFinal ? formatTime(currentResult.elapsed_seconds ?? 0) : `${formatTime(elapsedLive)} ⏱`}
                    </span>
                </div>
            </div>

            {/* Metrics row */}
            <div className="px-6 py-4 grid grid-cols-3 gap-4 border-b border-slate-700/50">
                <div className="text-center">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Final Score</p>
                    <p className="text-4xl font-black text-blue-400 leading-none">{(scoring?.final_ci_score ?? 0).toFixed(1)}</p>
                </div>
                <div className="text-center">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Bugs Fixed</p>
                    <p className="text-4xl font-black text-emerald-400 leading-none">{total_fixes ?? 0}</p>
                </div>
                <div className="text-center">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Failures</p>
                    <p className="text-4xl font-black text-red-400 leading-none">{total_failures ?? 0}</p>
                </div>
            </div>

            {/* Score Breakdown + bars (requirement #3) */}
            <div className="px-6 py-4 space-y-3">
                <h3 className="text-[11px] font-black uppercase tracking-widest text-slate-400 flex items-center gap-1.5 mb-3">
                    <BarChart3 className="w-3.5 h-3.5" /> Score Breakdown
                </h3>

                <div className="space-y-2.5">
                    <ScoreBar label="Base Score" value={scoring?.base_score ?? 0} bar={baseBar} color="from-slate-400 to-slate-300" textColor="text-slate-300" prefix="" />
                    <ScoreBar label="Speed Bonus" value={scoring?.speed_factor ?? 0} bar={speedBar} color="from-emerald-600 to-emerald-400" textColor="text-emerald-300" prefix="+" />
                    <ScoreBar label="Regression Penalty" value={scoring?.regression_penalty ?? 0} bar={penaltyBar} color="from-red-700 to-red-500" textColor="text-red-300" prefix="-" />
                    <div className="h-px bg-slate-700/60 my-1" />
                    <div className="flex items-center justify-between">
                        <span className="text-[11px] font-black uppercase tracking-widest text-slate-300">Final CI Score</span>
                        <span className="text-xl font-black text-blue-400">{(scoring?.final_ci_score ?? 0).toFixed(1)}</span>
                    </div>
                    <div className="w-full bg-slate-700/40 rounded-full h-3 overflow-hidden">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-blue-700 to-blue-400 transition-all duration-1000"
                            style={{ width: `${finalBar}%` }}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

interface ScoreBarProps {
    label: string;
    value: number;
    bar: number;
    color: string;
    textColor: string;
    prefix: string;
}

const ScoreBar = ({ label, value, bar, color, textColor, prefix }: ScoreBarProps) => (
    <div>
        <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-slate-400">{label}</span>
            <span className={`text-[11px] font-bold font-mono ${textColor}`}>{prefix}{value?.toFixed ? value.toFixed(1) : value}</span>
        </div>
        <div className="w-full bg-slate-700/40 rounded-full h-1.5 overflow-hidden">
            <div
                className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`}
                style={{ width: `${bar}%` }}
            />
        </div>
    </div>
);

export default ScorePanel;
