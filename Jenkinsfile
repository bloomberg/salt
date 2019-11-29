def unique_container_name = "unit-tests-${env.BUILD_ID}${env.JOB_NAME.replace("/", "-")}"
def image_name = "artprod.dev.bloomberg.com/bb-inf/salt-minion:2018.3.3"

// Without this both env.CHANGE_ID 1 and 10 will both be .1
// With change 1 will be .01 and 10 will be .1
def change_id = (env.CHANGE_ID < 10) ? "0${env.CHANGE_ID}" : env.CHANGE_ID

pipeline {
    agent { label 'syscore-salt'}
    environment {
        BBGH_TOKEN = credentials('bbgithub_token')
        PYPI_CREDENTIAL = credentials('salt_jenkins_ad_user_pass_escaped')
    }
    triggers {
        // Run once an hour between 4am-5am this pipeline will run on all salt prs but NOT master
        // Run multiple times incase artifactory changes when they remove builds and also if there are any failures pushing to artifactory
        cron(env.BRANCH_NAME == 'v2018.3.3-ca' ? '': '0 4-5 * * *')
    }
    options {
        ansiColor('xterm')
        // Keep up to 10 builds (artifacts/console output) from master and each branch retains up to 5 builds of that specific branch
        buildDiscarder(logRotator(numToKeepStr: env.BRANCH_NAME == 'v2018.3.3-ca' ? '10' : '5'))
    }
    stages {
        stage('Build') {
            when {changeRequest()}
            steps {
                sh "bash ./build/build.sh -b ${change_id}"
            }
        }
        stage('Run Upstream Salt Unit Tests') {
            when {changeRequest()}
            steps {
                script {
                    // We are running inside a container so we can have the bbcpu.lst/alias
                    docker.withRegistry('https://artprod.dev.bloomberg.com', 'syscore_jenkins_docker_jwt_tuple') {
                        sh "docker pull ${image_name}"
                    }
                    // Jenkins docker integration is confusing wrapper and doesn't seem to work as expected
                    sh "docker run --name ${unique_container_name} -d -v `pwd`:`pwd`:ro -w `pwd` ${image_name}"
                    sh "docker exec ${unique_container_name} pip install -r requirements/dev_bloomberg.txt"

                    // Run whatever tests you want here for now. All tests takes like an hour.
                    // If you write custom tests, add them here so we are sure they continue passing

                    sh "docker exec ${unique_container_name} pytest -l -n30 -q --color=yes tests/unit"

                    // Whatever is failing we can skip with
                    // @expectedFailure #bb test was failing when ran in Jenkins
                }
            }
            post {
                cleanup {
                    script {
                        sh "docker stop ${unique_container_name}"
                    }
                }
            }
        }
        stage('Deploy to dev pypi') {
            when {changeRequest()}
            steps {
                // This will build the dev pypi package as the (pr_number _ jenkins_build_number)
                // Also push/override the original pr_number
                //  |- If you want to install the latest dev build of a pr, just use pr number
                sh "bash ./build/build.sh -b ${env.CHANGE_ID} -k -s -u"
                sh "bash ./build/build.sh -b ${env.CHANGE_ID}.${change_id} -k -u"  // no -s so we build
            }
        }
        stage('Deploy to ose pypi') {
            when {anyOf {branch 'v2018.3.3-ca'}}
            steps {
                sh 'bash ./build/build.sh -u -p -t $BBGH_TOKEN_PSW'
            }
        }
    }
    post {
        cleanup {
            deleteDir() /* clean up our workspace */
        }
    }
}
