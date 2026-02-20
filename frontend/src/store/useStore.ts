import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import axios from 'axios';

const isProd = typeof import.meta !== 'undefined' && (import.meta as any).env?.PROD;
const API_URL = (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_API_URL) || (isProd ? '/api' : 'http://localhost:8000');

export interface Fix {
    file_path: string;
    error_type: string;
    original_snippet: string;
    patched_snippet: string;
    tests_passed: boolean;
    line_number?: number | null;
    commit_message?: string | null;
}

export interface Scoring {
    base_score: number;
    speed_factor: number;
    fix_efficiency: number;
    regression_penalty: number;
    final_ci_score: number;
}

export interface RunResult {
    repo_url: string;
    branch_name: string;
    run_id: string;
    total_failures: number;
    total_fixes: number;
    ci_status: string;
    fixes: Fix[];
    ci_timeline: string[];
    scoring: Scoring;
    start_time?: number;
    elapsed_seconds?: number;
    team_name?: string;
    leader_name?: string;
}

export interface RunHistoryItem {
    run_id: string;
    repo_url: string;
    branch_name: string;
    ci_status: string;
    total_fixes: number;
}

interface AppState {
    repoUrl: string;
    teamName: string;
    leaderName: string;
    branchName: string;
    isLoading: boolean;
    error: string | null;
    runId: string | null;
    runHistory: RunHistoryItem[];
    currentResult: RunResult | null;
    pollingIntervalId: any;

    setRepoUrl: (url: string) => void;
    setTeamName: (name: string) => void;
    setLeaderName: (name: string) => void;
    setBranchName: (name: string) => void;
    runAgent: () => Promise<void>;
    startPolling: () => void;
    stopPolling: () => void;
    fetchRuns: () => Promise<void>;
    selectRun: (runId: string) => Promise<void>;
    clearHistory: () => void;
    reset: () => void;
}

const FINAL_STATUSES = ['RESOLVED', 'FAILED', 'PARTIAL'];
const ACTIVE_STATUSES = ['PENDING', 'QUEUED', 'IN_PROGRESS', 'RUNNING'];

export const useStore = create<AppState>()(
    persist(
        (set, get) => ({
            repoUrl: '',
            teamName: '',
            leaderName: '',
            branchName: '',
            isLoading: false,
            error: null,
            runId: null,
            runHistory: [],
            currentResult: null,
            pollingIntervalId: null,

            setRepoUrl: (url) => set({ repoUrl: url }),

            setTeamName: (name) => {
                set({ teamName: name, error: null });
                const { leaderName } = get();
                const t = name.trim().toUpperCase().replace(/\s+/g, '_');
                const l = leaderName.trim().toUpperCase().replace(/\s+/g, '_');
                if (t && l) set({ branchName: `${t}_${l}_AI_FIX` });
            },

            setLeaderName: (name) => {
                set({ leaderName: name, error: null });
                const { teamName } = get();
                const t = teamName.trim().toUpperCase().replace(/\s+/g, '_');
                const l = name.trim().toUpperCase().replace(/\s+/g, '_');
                if (t && l) set({ branchName: `${t}_${l}_AI_FIX` });
            },

            setBranchName: (name) => set({ branchName: name }),

            runAgent: async () => {
                const { repoUrl, teamName, leaderName, branchName } = get();
                if (!repoUrl || !teamName || !leaderName) {
                    set({ error: 'Repository URL, Team Name, and Leader Name are all required.' });
                    return;
                }

                set({ isLoading: true, error: null, currentResult: null, runId: null });

                try {
                    const response = await axios.post(`${API_URL}/run-agent`, {
                        repo_url: repoUrl,
                        branch_name: branchName,
                        team_name: teamName,
                        leader_name: leaderName,
                    });

                    const newRunId = response.data.run_id;
                    const branch = response.data.branch_name || branchName;

                    // Optimistic immediate result (shown in UI right away)
                    const tempResult: RunResult = {
                        repo_url: repoUrl,
                        branch_name: branch,
                        run_id: newRunId,
                        total_failures: 0,
                        total_fixes: 0,
                        ci_status: 'PENDING',
                        fixes: [],
                        ci_timeline: ['Mission submitted to orchestrator...'],
                        scoring: { base_score: 100, speed_factor: 0, fix_efficiency: 0, regression_penalty: 0, final_ci_score: 0 },
                        start_time: Date.now() / 1000,
                        elapsed_seconds: 0,
                        team_name: teamName.toUpperCase(),
                        leader_name: leaderName.toUpperCase(),
                    };

                    set({ runId: newRunId, currentResult: tempResult, isLoading: false });
                    await get().fetchRuns();
                    get().startPolling();
                } catch (err: any) {
                    const msg = err.response?.data?.detail || err.message || 'Failed to start agent';
                    set({ isLoading: false, error: msg });
                }
            },

            fetchRuns: async () => {
                try {
                    const response = await axios.get(`${API_URL}/runs?_t=${Date.now()}`);
                    if (Array.isArray(response.data)) {
                        set({ runHistory: response.data });
                    }
                    const { runId, currentResult } = get();
                    if (runId && (!currentResult || currentResult.run_id !== runId)) {
                        try {
                            const res = await axios.get(`${API_URL}/results/${runId}?_t=${Date.now()}`);
                            set({ currentResult: res.data });
                        } catch (_) {
                            // Keep optimistic
                        }
                    }
                } catch (err) {
                    console.error('fetchRuns failed', err);
                }
            },

            selectRun: async (id: string) => {
                get().stopPolling();
                set({ runId: id, isLoading: true, error: null });
                try {
                    const response = await axios.get(`${API_URL}/results/${id}?_t=${Date.now()}`);
                    set({ currentResult: response.data, isLoading: false });
                    if (ACTIVE_STATUSES.includes(response.data.ci_status)) {
                        get().startPolling();
                    }
                } catch (err) {
                    set({ error: 'Failed to load run details.', isLoading: false });
                }
            },

            stopPolling: () => {
                const { pollingIntervalId } = get();
                if (pollingIntervalId) {
                    clearInterval(pollingIntervalId);
                    set({ pollingIntervalId: null });
                }
            },

            startPolling: () => {
                get().stopPolling();
                const { runId } = get();
                if (!runId) return;

                const id = window.setInterval(async () => {
                    const { runId: currentId } = get();
                    if (!currentId) { get().stopPolling(); return; }

                    get().fetchRuns();

                    try {
                        const response = await axios.get(`${API_URL}/results/${currentId}?_t=${Date.now()}`);
                        const result = response.data;
                        set({ currentResult: result });

                        if (FINAL_STATUSES.includes(result.ci_status)) {
                            set({ isLoading: false });
                            get().stopPolling();
                        }
                    } catch (_) {
                        // Transient — keep polling
                    }
                }, 2500);

                set({ pollingIntervalId: id });
            },

            clearHistory: () => {
                get().stopPolling();
                set({ runHistory: [], currentResult: null, runId: null, isLoading: false, error: null });
            },

            reset: () => {
                get().stopPolling();
                set({
                    repoUrl: '', teamName: '', leaderName: '', branchName: '',
                    isLoading: false, error: null, runId: null, currentResult: null, runHistory: [],
                });
            },
        }),
        {
            name: 'healing-agent-v3',
            partialize: (state) => ({
                repoUrl: state.repoUrl,
                teamName: state.teamName,
                leaderName: state.leaderName,
                branchName: state.branchName,
                runId: state.runId,
                currentResult: state.currentResult,
                runHistory: state.runHistory,
            }),
        }
    )
);
