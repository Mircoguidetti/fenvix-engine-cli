set -x
export PM_WORK=/tmp/pm-p0
E=/home/user/fenvix-engine-cli
cd $E/harness/parallel_measure
rm -rf /tmp/pm-p0/after
date -u
python3 measure.py --spec specs.json --name agentic-qe --reps 1 --first-rep 1 --workers 2,4 --timeout 14400 --skip plain_par,par --out /tmp/pm-p0/after; echo "AQE1 exit $?"; date -u
python3 measure.py --spec specs.json --name agentic-qe --reps 1 --first-rep 1 --workers 2 --timeout 14400 --skip plain_par,plain,serial --out /tmp/pm-p0/after; echo "AQE2 exit $?"; date -u
python3 measure.py --spec specs.json --name agentic-qe --reps 1 --first-rep 1 --workers 4 --timeout 14400 --skip plain_par,plain,serial --out /tmp/pm-p0/after; echo "AQE3 exit $?"; date -u
python3 measure.py --spec specs.json --name ironcurtain --reps 1 --workers 2,4 --skip plain_par --out /tmp/pm-p0/after; echo "IC exit $?"; date -u
cd $E
python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0/after agentic-qe --phase after; echo "CHECK_AQE exit $?"
python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0/after ironcurtain --phase after; echo "CHECK_IC exit $?"
cd /tmp/pm-p0/after/agentic-qe && /usr/bin/time -v /tmp/pm-p0/venv/networkx/bin/python -m detpy.fenvix verify S1.jsonl P1w4.jsonl --json > /tmp/pm-p0/verify-S1-P1w4.json 2> /tmp/pm-p0/verify-S1-P1w4.time; echo "VERIFY exit $?"
grep -E "Maximum resident|Elapsed|Exit status" /tmp/pm-p0/verify-S1-P1w4.time
ls -la /tmp/pm-p0/after/agentic-qe /tmp/pm-p0/after/ironcurtain
echo REMEASURE_DONE
