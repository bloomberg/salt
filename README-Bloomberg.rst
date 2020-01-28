# To run tests

docker pull artprod.dev.bloomberg.com/bb-inf/salt-minion:2018.3.3
docker run --name i-love-salt -d -v `pwd`:`pwd`:ro -w `pwd` artprod.dev.bloomberg.com/bb-inf/salt-minion:2018.3.3
docker exec i-love-salt pip install -r requirements/dev_bloomberg.txt
docker exec i-love-salt pytest -l -n1 -q --color=yes tests/unit -k "BaseHighStateTestCase"