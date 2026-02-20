import React, { useEffect } from 'react';
import { useStore } from './store/useStore';
import InputPanel from './components/InputPanel';
import ScorePanel from './components/ScorePanel';
import FixTable from './components/FixTable';
import Timeline from './components/Timeline';
import RunHistoryPanel from './components/RunHistoryPanel';
import { BrainCircuit, ShieldCheck, Zap, Activity, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';

function App() {
    const { currentResult, runId, startPolling, fetchRuns, isLoading, error } = useStore();

    useEffect(() => {
        fetchRuns();
        if (runId) startPolling();
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const isActive = !!(currentResult && ['PENDING', 'QUEUED', 'IN_PROGRESS', 'RUNNING'].includes(currentResult.ci_status));
    const isFinal = !!(currentResult && ['RESOLVED', 'FAILED', 'PARTIAL'].includes(currentResult.ci_status));

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-blue-500/30">

            {/* ───── Header ───── */}
            <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
                <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="bg-gradient-to-br from-blue-600 to-blue-700 p-2 rounded-xl shadow-lg shadow-blue-500/20 border border-blue-400/20">
                            <BrainCircuit className="w-6 h-6 text-white" />
                        </div>
                        <div>
                            <h1 className="text-lg font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-cyan-300 to-blue-500">
                                Autonomous CI/CD Healing Core <span className="text-[10px] opacity-70 font-mono ml-2 border border-blue-500/30 px-1.5 py-0.5 rounded text-blue-400">PRO LIVE (v1.12)</span>
                                <span className="text-[8px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-1 ml-2 rounded uppercase tracking-tighter font-black">GHA Core</span>
                            </h1>
                            <div className="flex items-center gap-3 text-[10px] font-bold text-slate-600 tracking-widest uppercase">
                                <span className="flex items-center gap-1"><ShieldCheck className="w-2.5 h-2.5 text-emerald-500" /> Multi-Agent</span>
                                <span className="flex items-center gap-1"><Zap className="w-2.5 h-2.5 text-yellow-500" /> LangGraph</span>
                                <span className="flex items-center gap-1"><Activity className="w-2.5 h-2.5 text-blue-500" /> Self-Healing CI/CD</span>
                            </div>
                        </div>
                    </div>

                    {/* Live status chip in header */}
                    {currentResult && (
                        <div className={`flex items-center gap-2 px-4 py-2 rounded-full text-[11px] font-black border uppercase tracking-widest ${currentResult.ci_status === 'RESOLVED' ? 'bg-emerald-900/30 text-emerald-400 border-emerald-700/50' :
                            currentResult.ci_status === 'PARTIAL' ? 'bg-amber-900/30 text-amber-400 border-amber-700/50' :
                                currentResult.ci_status === 'FAILED' ? 'bg-red-900/30 text-red-400 border-red-700/50' :
                                    isActive ? 'bg-blue-900/30 text-blue-400 border-blue-700/50 animate-pulse' :
                                        'bg-slate-800 text-slate-400 border-slate-700'
                            }`}>
                            {currentResult.ci_status === 'RESOLVED' && <CheckCircle2 className="w-3.5 h-3.5" />}
                            {currentResult.ci_status === 'PARTIAL' && <CheckCircle2 className="w-3.5 h-3.5 opacity-70" />}
                            {currentResult.ci_status === 'FAILED' && <AlertCircle className="w-3.5 h-3.5" />}
                            {isActive && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            {currentResult.ci_status}
                        </div>
                    )}
                </div>
            </header>

            {/* ───── Main Grid ───── */}
            <main className="max-w-[1400px] mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">

                {/* Left panel (1/4) */}
                <div className="lg:col-span-1 space-y-5 lg:sticky lg:top-[76px]">
                    <InputPanel />
                    <RunHistoryPanel />

                    <div className="bg-slate-900/40 p-4 rounded-2xl border border-slate-800/60 text-xs text-slate-500 space-y-2 leading-relaxed">
                        <p className="font-bold text-slate-400 text-[11px] uppercase tracking-widest">⚙ Agent Specs</p>
                        <p>Each run: isolated sandbox · AST analysis · dynamic test execution · up to <strong className="text-slate-300">5 retry iterations</strong> · LangGraph multi-agent orchestration.</p>
                        <p>Branch naming: <code className="text-blue-300/70 bg-slate-800 px-1 rounded text-[10px]">TEAM_LEADER_AI_FIX</code></p>
                        <p>Commits are prefixed with <code className="text-blue-300/70 bg-slate-800 px-1 rounded text-[10px]">[AI-AGENT]</code>.</p>
                    </div>
                </div>

                {/* Right panel (3/4) */}
                <div className="lg:col-span-3 space-y-6">

                    {/* Mission identifier banner */}
                    {currentResult ? (
                        <div className={`flex items-center justify-between p-5 rounded-2xl border shadow-2xl backdrop-blur-sm transition-all ${isActive ? 'bg-blue-950/30 border-blue-700/40 border-l-4 border-l-blue-500' :
                            currentResult.ci_status === 'RESOLVED' ? 'bg-emerald-950/20 border-emerald-700/40 border-l-4 border-l-emerald-500' :
                                currentResult.ci_status === 'PARTIAL' ? 'bg-amber-950/20 border-amber-700/40 border-l-4 border-l-amber-500' :
                                    'bg-red-950/20 border-red-700/40 border-l-4 border-l-red-500'
                            }`}>
                            <div className="min-w-0 flex-1">
                                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-0.5">Mission Identifier</p>
                                <p className="text-lg font-black text-slate-100 font-mono truncate tracking-tight" title={currentResult.run_id}>
                                    {currentResult.run_id}
                                </p>
                                <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                                    Target: <span className="text-slate-400">{currentResult.repo_url}</span>
                                </p>
                            </div>
                            <div className="pl-4 flex-shrink-0">
                                <span className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-[11px] font-black border uppercase tracking-widest shadow-lg ${currentResult.ci_status === 'RESOLVED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/40' :
                                    currentResult.ci_status === 'PARTIAL' ? 'bg-amber-500/10 text-amber-400 border-amber-500/40' :
                                        currentResult.ci_status === 'FAILED' ? 'bg-red-500/10 text-red-400 border-red-500/40' :
                                            ['PENDING', 'QUEUED'].includes(currentResult.ci_status) ? 'bg-amber-500/10 text-amber-400 border-amber-500/40 animate-pulse' :
                                                'bg-blue-500/10 text-blue-400 border-blue-500/40 animate-pulse'
                                    }`}>
                                    {isActive && <Loader2 className="w-3 h-3 animate-spin" />}
                                    {currentResult.ci_status === 'RESOLVED' && <CheckCircle2 className="w-3 h-3" />}
                                    {currentResult.ci_status === 'PARTIAL' && <CheckCircle2 className="w-3 h-3 opacity-70" />}
                                    {currentResult.ci_status}
                                </span>
                            </div>
                        </div>
                    ) : (
                        !isLoading && (
                            <div className="h-56 flex flex-col items-center justify-center border-2 border-dashed border-slate-800/60 rounded-2xl bg-slate-900/20 group hover:bg-slate-900/30 transition-all">
                                <div className="bg-slate-800/50 p-6 rounded-full mb-5 border border-slate-700 group-hover:scale-105 transition-transform duration-500">
                                    <Activity className="w-12 h-12 text-slate-600 group-hover:text-blue-500 transition-colors" />
                                </div>
                                <h3 className="text-slate-300 font-black mb-2 text-xl tracking-tight">Intelligence Core Idle</h3>
                                <p className="text-slate-500 text-sm text-center max-w-sm px-8 leading-relaxed">
                                    Enter a GitHub repository URL, team name, and leader name —<br />
                                    then click <span className="text-blue-400 font-bold">Run Healing Agent</span> to begin.
                                </p>
                            </div>
                        )
                    )}

                    {/* Error state */}
                    {error && (
                        <div className="bg-red-500/10 border border-red-500/20 p-4 rounded-xl text-red-400 text-sm flex items-center gap-3">
                            <AlertCircle className="w-5 h-5 flex-shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    {/* Content panels */}
                    {currentResult && (
                        <>
                            <ScorePanel />
                            <FixTable />
                            <Timeline />
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}

export default App;
