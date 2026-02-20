import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import { Play, Loader2, GitBranch, Link, Users, User, Trash2 } from 'lucide-react';

const InputPanel = () => {
    const {
        repoUrl, teamName, leaderName, branchName,
        setRepoUrl, setTeamName, setLeaderName,
        runAgent, isLoading, error, clearHistory, currentResult
    } = useStore();

    const [localError, setLocalError] = useState('');

    const handleRun = () => {
        if (!repoUrl.trim() || !teamName.trim() || !leaderName.trim()) {
            setLocalError('All three fields are required.');
            return;
        }
        if (!repoUrl.startsWith('http')) {
            setLocalError('Repository URL must start with http(s)://');
            return;
        }
        setLocalError('');
        runAgent();
    };

    const isActive = !!(currentResult && !['RESOLVED', 'FAILED'].includes(currentResult.ci_status));

    return (
        <div className="bg-gradient-to-b from-slate-800 to-slate-800/80 p-6 rounded-2xl shadow-2xl border border-slate-700/60">
            <h2 className="text-base font-black text-slate-100 mb-5 flex items-center gap-2 uppercase tracking-widest">
                🚀 Mission Control
            </h2>

            <div className="space-y-3">
                {/* Repo URL */}
                <div>
                    <label className="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-widest flex items-center gap-1.5">
                        <Link className="w-3 h-3" /> GitHub Repository URL
                    </label>
                    <input
                        type="text"
                        id="repo-url-input"
                        value={repoUrl}
                        onChange={(e) => setRepoUrl(e.target.value)}
                        placeholder="https://github.com/owner/repo"
                        disabled={isLoading}
                        className="w-full bg-slate-900/80 border border-slate-700 rounded-xl px-4 py-2.5 text-slate-200 text-sm focus:ring-2 focus:ring-blue-500/60 focus:border-blue-500/60 outline-none transition-all placeholder:text-slate-600 disabled:opacity-50"
                    />
                </div>

                {/* Team + Leader */}
                <div className="grid grid-cols-2 gap-3">
                    <div>
                        <label className="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-widest flex items-center gap-1.5">
                            <Users className="w-3 h-3" /> Team Name
                        </label>
                        <input
                            type="text"
                            id="team-name-input"
                            value={teamName}
                            onChange={(e) => setTeamName(e.target.value)}
                            placeholder="e.g. RIFT"
                            disabled={isLoading}
                            className="w-full bg-slate-900/80 border border-slate-700 rounded-xl px-3 py-2.5 text-slate-200 text-sm focus:ring-2 focus:ring-blue-500/60 outline-none transition-all placeholder:text-slate-600 disabled:opacity-50 uppercase"
                        />
                    </div>
                    <div>
                        <label className="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-widest flex items-center gap-1.5">
                            <User className="w-3 h-3" /> Leader Name
                        </label>
                        <input
                            type="text"
                            id="leader-name-input"
                            value={leaderName}
                            onChange={(e) => setLeaderName(e.target.value)}
                            placeholder="e.g. HARSH"
                            disabled={isLoading}
                            className="w-full bg-slate-900/80 border border-slate-700 rounded-xl px-3 py-2.5 text-slate-200 text-sm focus:ring-2 focus:ring-blue-500/60 outline-none transition-all placeholder:text-slate-600 disabled:opacity-50 uppercase"
                        />
                    </div>
                </div>

                {/* Branch Preview */}
                <div>
                    <label className="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-widest flex items-center gap-1.5">
                        <GitBranch className="w-3 h-3" /> Branch (Auto-Generated)
                    </label>
                    <div className="w-full bg-slate-900/40 border border-slate-700/50 rounded-xl px-4 py-2.5 text-xs text-blue-300/80 font-mono tracking-wide min-h-[38px] flex items-center">
                        {branchName || <span className="text-slate-600">Fill team & leader to preview...</span>}
                    </div>
                </div>

                {/* Errors */}
                {(localError || error) && (
                    <div className="text-red-400 text-xs bg-red-900/20 p-3 rounded-lg border border-red-900/40 leading-relaxed">
                        ⚠ {localError || error}
                    </div>
                )}

                {/* Active run warning */}
                {isActive && (
                    <div className="text-amber-400 text-xs bg-amber-900/20 p-2.5 rounded-lg border border-amber-900/40">
                        🔄 A run is already in progress. Starting a new run will track it separately.
                    </div>
                )}

                {/* Run Button */}
                <button
                    id="run-agent-btn"
                    onClick={handleRun}
                    disabled={isLoading}
                    className="w-full bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-cyan-500 text-white font-black py-3 rounded-xl transition-all flex items-center justify-center gap-2.5 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-500/20 text-sm tracking-wide uppercase"
                >
                    {isLoading ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Deploying Agent...
                        </>
                    ) : (
                        <>
                            <Play className="w-4 h-4" />
                            Run Healing Agent
                        </>
                    )}
                </button>

                {/* Clear history */}
                <button
                    id="clear-history-btn"
                    onClick={clearHistory}
                    disabled={isLoading}
                    className="w-full text-slate-500 hover:text-red-400 text-xs font-medium py-1.5 flex items-center justify-center gap-1.5 transition-colors disabled:opacity-30"
                >
                    <Trash2 className="w-3 h-3" /> Clear History
                </button>
            </div>
        </div>
    );
};

export default InputPanel;
